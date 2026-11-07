import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import Chunk, DocumentPage, Requirement, Run, Tender
from app.db.session import get_sessionmaker
from tests.integration.ingestion.conftest import (
    API,
    auth,
    docx_file,
    new_tender,
    pdf_file,
    stored_files,
    upload,
)
from tests.unit.ingestion import samples

THREE_PAGES = [
    "1. Introduction\nThe Ministry invites sealed bids for campus networking.",
    "2. Bill Of Quantities\nThe items below are required.",
    "3. Eligibility Criteria\nBidders must have completed three similar projects.",
]


# --- tenders ----------------------------------------------------------------------------------


async def test_create_list_and_get_tender(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    resp = await client.post(f"{API}/tenders", json={"title": "Campus LAN"}, headers=h)
    assert resp.status_code == 201
    tender = resp.json()["tender"]
    assert tender["status"] == "DRAFT" and tender["title"] == "Campus LAN"

    no_body = await client.post(f"{API}/tenders", headers=h)
    assert no_body.status_code == 201 and no_body.json()["tender"]["title"] is None

    listed = await client.get(f"{API}/tenders", headers=h)
    assert listed.status_code == 200
    assert listed.json()["total"] == 2 and len(listed.json()["items"]) == 2

    detail = await client.get(f"{API}/tenders/{tender['id']}", headers=h)
    assert detail.status_code == 200
    assert detail.json() == {
        "tender": detail.json()["tender"],
        "documents": [],
        "latest_run": None,
    }


async def test_list_tenders_pagination_and_status_filter(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    ids = [await new_tender(client, h, f"T{i}") for i in range(5)]
    async with get_sessionmaker()() as s:
        tender = await s.get(Tender, uuid.UUID(ids[0]))
        assert tender is not None
        tender.status = "APPROVED"
        await s.commit()

    page = await client.get(f"{API}/tenders", params={"page": 2, "page_size": 2}, headers=h)
    assert page.json()["total"] == 5 and len(page.json()["items"]) == 2

    approved = await client.get(f"{API}/tenders", params={"status": "APPROVED"}, headers=h)
    assert approved.json()["total"] == 1 and approved.json()["items"][0]["id"] == ids[0]

    bad = await client.get(f"{API}/tenders", params={"status": "NOPE"}, headers=h)
    assert bad.status_code == 422
    too_big = await client.get(f"{API}/tenders", params={"page_size": 1000}, headers=h)
    assert too_big.status_code == 422


async def test_tender_detail_includes_latest_run(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    me = (await client.get(f"{API}/me", headers=h)).json()
    org_id = uuid.UUID(me["organisation"]["id"])
    async with get_sessionmaker()() as s:
        s.add(
            Run(
                organisation_id=org_id,
                tender_id=uuid.UUID(tender_id),
                thread_id="t-1",
                status="FAILED",
            )
        )
        await s.commit()
        s.add(
            Run(
                organisation_id=org_id,
                tender_id=uuid.UUID(tender_id),
                thread_id="t-2",
                status="RUNNING",
            )
        )
        await s.commit()
    detail = (await client.get(f"{API}/tenders/{tender_id}", headers=h)).json()
    run = detail["latest_run"]
    assert run["status"] == "RUNNING" and run["tender_id"] == tender_id
    assert run["cost_usd"] == 0 and run["budget_usd"] == 5.0
    assert run["tokens_in"] == 0 and run["tokens_out"] == 0


async def test_dashboard_stats(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    ids = [await new_tender(client, h) for _ in range(4)]
    async with get_sessionmaker()() as s:
        for tid, status in zip(
            ids, ["AWAITING_REVIEW", "AWAITING_REVIEW", "APPROVED"], strict=False
        ):
            tender = await s.get(Tender, uuid.UUID(tid))
            assert tender is not None
            tender.status = status
        await s.commit()
    stats = await client.get(f"{API}/dashboard/stats", headers=h)
    assert stats.json() == {"tenders": 4, "awaiting_review": 2, "approved": 1}

    other = await auth(client, "b@example.com", org="Org B")
    assert (await client.get(f"{API}/dashboard/stats", headers=other)).json() == {
        "tenders": 0,
        "awaiting_review": 0,
        "approved": 0,
    }


async def test_endpoints_require_auth(client: AsyncClient) -> None:
    some = uuid.uuid4()
    for method, path in [
        ("POST", "/tenders"),
        ("GET", "/tenders"),
        ("GET", f"/tenders/{some}"),
        ("POST", f"/tenders/{some}/documents"),
        ("POST", "/knowledge-base/documents"),
        ("GET", "/knowledge-base/documents"),
        ("DELETE", f"/documents/{some}"),
        ("GET", f"/documents/{some}/pages/1"),
        ("GET", "/dashboard/stats"),
    ]:
        resp = await client.request(method, f"{API}{path}")
        assert resp.status_code == 401, (method, path)


# --- upload + extraction ----------------------------------------------------------------------


async def test_upload_pdf_extracts_pages_tables_and_chunks(
    client: AsyncClient, storage_dir: Path
) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    data = samples.pdf_bytes(THREE_PAGES, table_on_page=2)
    resp = await upload(client, h, tender_id, [pdf_file(data, "C:\\fakepath\\tender.pdf")])
    assert resp.status_code == 201, resp.text
    doc = resp.json()["documents"][0]
    assert doc["filename"] == "tender.pdf"
    assert doc["mime_type"] == "application/pdf"
    assert doc["extraction_status"] == "DONE" and doc["page_count"] == 3
    assert doc["size_bytes"] == len(data)
    import hashlib

    assert doc["sha256"] == hashlib.sha256(data).hexdigest()

    # stored under a UUID name, not the client file name (S-04)
    stored = stored_files(storage_dir)
    assert len(stored) == 1 and stored[0].name != "tender.pdf"
    assert stored[0].read_bytes() == data

    page2 = await client.get(f"{API}/documents/{doc['id']}/pages/2", headers=h)
    assert page2.status_code == 200
    body = page2.json()
    assert body["page_no"] == 2 and body["page_count"] == 3 and body["ocr_used"] is False
    assert "Bill Of Quantities" in body["text"]
    assert body["tables"] == [{"rows": samples.TABLE_ROWS}]

    missing = await client.get(f"{API}/documents/{doc['id']}/pages/9", headers=h)
    assert missing.status_code == 404

    async with get_sessionmaker()() as s:
        chunks = (
            (await s.execute(select(Chunk).where(Chunk.document_id == uuid.UUID(doc["id"]))))
            .scalars()
            .all()
        )
    by_heading = {c.section_heading: c for c in chunks}
    assert by_heading["3. Eligibility Criteria"].page_start == 3
    assert by_heading["1. Introduction"].page_end == 1
    assert all(c.embedding is None for c in chunks)  # upload ingests with llm=None

    detail = (await client.get(f"{API}/tenders/{tender_id}", headers=h)).json()
    assert [d["id"] for d in detail["documents"]] == [doc["id"]]


async def test_upload_docx_and_addenda_numbering(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    docx_data = samples.docx_bytes([("h1", "Addendum No. 1"), ("p", "Deadline extended.")])
    first = await upload(client, h, tender_id, [docx_file(docx_data)], kind="ADDENDUM")
    assert first.status_code == 201, first.text
    d = first.json()["documents"][0]
    assert d["mime_type"].endswith("wordprocessingml.document")
    assert d["extraction_status"] == "DONE" and d["page_count"] == 1
    assert d["addendum_seq"] == 1

    two = await upload(
        client,
        h,
        tender_id,
        [docx_file(docx_data, "a.docx"), docx_file(docx_data, "b.docx")],
        kind="ADDENDUM",
    )
    assert [x["addendum_seq"] for x in two.json()["documents"]] == [2, 3]

    explicit = await upload(
        client, h, tender_id, [docx_file(docx_data)], kind="ADDENDUM", addendum_seq="7"
    )
    assert explicit.json()["documents"][0]["addendum_seq"] == 7

    page = await client.get(f"{API}/documents/{d['id']}/pages/1", headers=h)
    assert "Deadline extended." in page.json()["text"]


async def test_upload_form_validation(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    pdf = [pdf_file(samples.pdf_bytes(["x"]))]
    assert (await upload(client, h, tender_id, pdf, kind="BOGUS")).status_code == 422
    seq_on_tender = await upload(client, h, tender_id, pdf, kind="TENDER", addendum_seq="2")
    assert seq_on_tender.status_code == 422
    zero_seq = await upload(client, h, tender_id, pdf, kind="ADDENDUM", addendum_seq="0")
    assert zero_seq.status_code == 422
    missing_files = await client.post(
        f"{API}/tenders/{tender_id}/documents", data={"kind": "TENDER"}, headers=h
    )
    assert missing_files.status_code == 422
    unknown = await upload(client, h, str(uuid.uuid4()), pdf)
    assert unknown.status_code == 404


async def test_upload_rejects_wrong_type_by_magic_bytes(
    client: AsyncClient, storage_dir: Path
) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    fake = [("files", ("tender.pdf", b"MZ\x90\x00 this is really an exe", "application/pdf"))]
    resp = await upload(client, h, tender_id, fake)
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert resp.json()["error"]["details"] == {"filename": "tender.pdf"}

    # A real PDF named .txt is accepted: the extension does not matter.
    ok = await upload(
        client, h, tender_id, [("files", ("x.txt", samples.pdf_bytes(["x"]), "text/plain"))]
    )
    assert ok.status_code == 201


async def test_upload_rejects_oversize(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_MB", 1)
    big = samples.pdf_bytes(["x"]) + b"\n%" + b"0" * (1024 * 1024)
    resp = await upload(client, h, tender_id, [pdf_file(big)])
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "FILE_TOO_LARGE"


async def test_upload_rejects_pdf_with_javascript_and_embedded_files(
    client: AsyncClient, storage_dir: Path
) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    for data in (samples.js_pdf(), samples.embedded_file_pdf()):
        resp = await upload(client, h, tender_id, [pdf_file(data)])
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "UNSAFE_PDF"


async def test_rejected_file_rolls_back_whole_batch(client: AsyncClient, storage_dir: Path) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    files = [
        pdf_file(samples.pdf_bytes(["good"]), "good.pdf"),
        pdf_file(samples.js_pdf(), "bad.pdf"),
    ]
    resp = await upload(client, h, tender_id, files)
    assert resp.status_code == 422
    assert resp.json()["error"]["details"] == {"filename": "bad.pdf"}
    detail = (await client.get(f"{API}/tenders/{tender_id}", headers=h)).json()
    assert detail["documents"] == []
    assert stored_files(storage_dir) == []


async def test_upload_rejects_too_many_files(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    data = samples.pdf_bytes(["x"])
    first = await upload(client, h, tender_id, [pdf_file(data, f"{i}.pdf") for i in range(29)])
    assert first.status_code == 201
    over = await upload(client, h, tender_id, [pdf_file(data, "a.pdf"), pdf_file(data, "b.pdf")])
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "TOO_MANY_FILES"
    last = await upload(client, h, tender_id, [pdf_file(data, "30.pdf")])
    assert last.status_code == 201

    other = await new_tender(client, h)
    too_many = await upload(client, h, other, [pdf_file(data, f"{i}.pdf") for i in range(31)])
    assert too_many.status_code == 422 and too_many.json()["error"]["code"] == "TOO_MANY_FILES"


async def test_scanned_pdf_without_ocr_is_partial_with_warning(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    resp = await upload(client, h, tender_id, [pdf_file(samples.mixed_pdf(2, 2))])
    assert resp.status_code == 201
    body = resp.json()
    assert body["documents"][0]["extraction_status"] == "PARTIAL"
    assert any("OCR unavailable" in w for w in body["warnings"])
    assert any("2 of 4 pages have no text" in w for w in body["warnings"])
    page = await client.get(f"{API}/documents/{body['documents'][0]['id']}/pages/3", headers=h)
    assert page.json()["ocr_used"] is False and page.json()["text"].strip() == ""


# --- knowledge base ---------------------------------------------------------------------------


async def test_knowledge_base_upload_and_list(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    data = samples.docx_bytes([("h1", "Company Profile"), ("p", "Founded 2009.")])
    resp = await client.post(
        f"{API}/knowledge-base/documents",
        files=[docx_file(data, "profile.docx")],
        data={"kind": "COMPANY_PROFILE"},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    doc = resp.json()["documents"][0]
    assert doc["tender_id"] is None and doc["kind"] == "COMPANY_PROFILE"

    tender_id = await new_tender(client, h)
    await upload(client, h, tender_id, [pdf_file(samples.pdf_bytes(["t"]))])

    listed = await client.get(f"{API}/knowledge-base/documents", headers=h)
    assert [d["id"] for d in listed.json()["items"]] == [doc["id"]]  # tender docs excluded

    bad_kind = await client.post(
        f"{API}/knowledge-base/documents",
        files=[docx_file(data)],
        data={"kind": "TENDER"},
        headers=h,
    )
    assert bad_kind.status_code == 422


# --- delete -----------------------------------------------------------------------------------


async def test_delete_document_cascades_and_removes_file(
    client: AsyncClient, storage_dir: Path
) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    resp = await upload(client, h, tender_id, [pdf_file(samples.pdf_bytes(THREE_PAGES))])
    doc_id = uuid.UUID(resp.json()["documents"][0]["id"])
    assert len(stored_files(storage_dir)) == 1

    deleted = await client.delete(f"{API}/documents/{doc_id}", headers=h)
    assert deleted.status_code == 204
    assert stored_files(storage_dir) == []
    async with get_sessionmaker()() as s:
        pages = await s.scalar(
            select(func.count()).select_from(DocumentPage).where(DocumentPage.document_id == doc_id)
        )
        chunks = await s.scalar(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
        )
    assert pages == 0 and chunks == 0
    assert (await client.delete(f"{API}/documents/{doc_id}", headers=h)).status_code == 404
    assert (await client.get(f"{API}/documents/{doc_id}/pages/1", headers=h)).status_code == 404


async def test_delete_document_cited_by_requirement_is_conflict(client: AsyncClient) -> None:
    h = await auth(client, "a@example.com")
    tender_id = await new_tender(client, h)
    resp = await upload(client, h, tender_id, [pdf_file(samples.pdf_bytes(THREE_PAGES))])
    doc = resp.json()["documents"][0]
    async with get_sessionmaker()() as s:
        s.add(
            Requirement(
                organisation_id=uuid.UUID(doc["organisation_id"]),
                tender_id=uuid.UUID(tender_id),
                req_code="ELG-001",
                category="ELIGIBILITY",
                description="Three similar projects",
                is_mandatory=True,
                source_document_id=uuid.UUID(doc["id"]),
                source_page=3,
            )
        )
        await s.commit()
    conflict = await client.delete(f"{API}/documents/{doc['id']}", headers=h)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "DOCUMENT_IN_USE"
    assert (await client.get(f"{API}/documents/{doc['id']}/pages/1", headers=h)).status_code == 200


# --- cross-organisation isolation (S-01) ------------------------------------------------------


async def test_cross_organisation_access_is_denied(client: AsyncClient) -> None:
    a = await auth(client, "a@example.com", org="Org A")
    b = await auth(client, "b@example.com", org="Org B")
    tender_a = await new_tender(client, a, "A's tender")
    up = await upload(client, a, tender_a, [pdf_file(samples.pdf_bytes(THREE_PAGES))])
    doc_a = up.json()["documents"][0]["id"]
    kb = await client.post(
        f"{API}/knowledge-base/documents",
        files=[docx_file(samples.docx_bytes([("p", "A profile")]))],
        data={"kind": "COMPANY_PROFILE"},
        headers=a,
    )
    kb_a = kb.json()["documents"][0]["id"]

    # org B cannot see, upload to, read pages of, or delete org A's resources
    assert (await client.get(f"{API}/tenders/{tender_a}", headers=b)).status_code == 404
    up_b = await upload(client, b, tender_a, [pdf_file(samples.pdf_bytes(["x"]))])
    assert up_b.status_code == 404
    for doc in (doc_a, kb_a):
        assert (await client.get(f"{API}/documents/{doc}/pages/1", headers=b)).status_code == 404
        assert (await client.delete(f"{API}/documents/{doc}", headers=b)).status_code == 404

    # lists are scoped
    assert (await client.get(f"{API}/tenders", headers=b)).json() == {"items": [], "total": 0}
    assert (await client.get(f"{API}/knowledge-base/documents", headers=b)).json() == {"items": []}

    # org A still has everything
    assert (await client.get(f"{API}/documents/{doc_a}/pages/1", headers=a)).status_code == 200
    assert (await client.get(f"{API}/documents/{kb_a}/pages/1", headers=a)).status_code == 200
    detail = (await client.get(f"{API}/tenders/{tender_a}", headers=a)).json()
    assert len(detail["documents"]) == 1
