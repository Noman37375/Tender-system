import uuid

import pytest
from sqlalchemy import select

from app.db.models import Chunk, Document, DocumentPage, Organisation
from app.db.session import get_sessionmaker
from app.ingestion import storage
from app.ingestion.pipeline import DocumentNotFoundError, ingest_document
from app.ingestion.validation import DOCX_MIME, PDF_MIME
from app.llm.fake import FakeLLMClient
from tests.unit.ingestion import samples


async def _org(name: str = "Org") -> uuid.UUID:
    async with get_sessionmaker()() as s:
        org = Organisation(name=name)
        s.add(org)
        await s.commit()
        return org.id


async def _document(org_id: uuid.UUID, data: bytes, mime: str = PDF_MIME) -> uuid.UUID:
    key = storage.save(data, mime)
    async with get_sessionmaker()() as s:
        doc = Document(
            organisation_id=org_id,
            kind="COMPANY_PROFILE",
            filename="f",
            mime_type=mime,
            size_bytes=len(data),
            sha256="x",
            storage_path=key,
        )
        s.add(doc)
        await s.commit()
        return doc.id


async def test_ingest_then_embed_only_missing_chunks() -> None:
    org = await _org()
    pages = [f"{i}. Section Number {i}\n" + ("text " * 900) for i in range(1, 4)]
    doc_id = await _document(org, samples.pdf_bytes(pages))

    async with get_sessionmaker()() as s:
        first = await ingest_document(s, org, doc_id, None)
    assert (first.extraction_status, first.page_count, first.warnings) == ("DONE", 3, [])

    async with get_sessionmaker()() as s:
        page_ids = set((await s.execute(select(DocumentPage.id))).scalars())
        chunks = (await s.execute(select(Chunk))).scalars().all()
        assert len(chunks) >= 3 and all(c.embedding is None for c in chunks)
        # pre-fill one embedding: the pipeline must not overwrite it
        keep = chunks[0]
        keep.embedding = [0.5] * 1536
        await s.commit()
        keep_id = keep.id

    llm = FakeLLMClient()
    async with get_sessionmaker()() as s:
        again = await ingest_document(s, org, doc_id, llm)
    assert again.extraction_status == "DONE" and again.page_count == 3

    async with get_sessionmaker()() as s:
        assert (
            set((await s.execute(select(DocumentPage.id))).scalars()) == page_ids
        )  # no re-extract
        chunks = (await s.execute(select(Chunk))).scalars().all()
        assert all(c.embedding is not None and len(c.embedding) == 1536 for c in chunks)
        kept = next(c for c in chunks if c.id == keep_id)
        assert list(kept.embedding) == [0.5] * 1536  # type: ignore[arg-type]


async def test_ingest_docx_uses_heading_styles() -> None:
    org = await _org()
    data = samples.docx_bytes(
        [
            ("h1", "Project Credentials"),
            ("p", "Campus network for University X, 2021."),
            ("h1", "Certifications"),
            ("p", "ISO 9001:2015 valid until 2027."),
        ]
    )
    doc_id = await _document(org, data, DOCX_MIME)
    async with get_sessionmaker()() as s:
        result = await ingest_document(s, org, doc_id, FakeLLMClient())
        chunks = (await s.execute(select(Chunk).where(Chunk.document_id == doc_id))).scalars().all()
    assert result.extraction_status == "DONE"
    assert sorted(c.section_heading or "" for c in chunks) == [
        "Certifications",
        "Project Credentials",
    ]
    assert all(c.embedding is not None for c in chunks)


async def test_unreadable_file_marks_failed() -> None:
    org = await _org()
    doc_id = await _document(org, b"%PDF-1.4 not really a pdf")
    async with get_sessionmaker()() as s:
        result = await ingest_document(s, org, doc_id, FakeLLMClient())
        doc = await s.get(Document, doc_id)
    assert result.extraction_status == "FAILED"
    assert result.warnings == ["Document f: extraction failed"]
    assert doc is not None and doc.extraction_status == "FAILED"


async def test_missing_stored_file_marks_failed() -> None:
    org = await _org()
    doc_id = await _document(org, samples.pdf_bytes(["x"]))
    async with get_sessionmaker()() as s:
        doc = await s.get(Document, doc_id)
        assert doc is not None
        storage.remove(doc.storage_path)
    async with get_sessionmaker()() as s:
        assert (await ingest_document(s, org, doc_id, None)).extraction_status == "FAILED"


async def test_partial_document_reports_warning_on_reingest() -> None:
    org = await _org()
    doc_id = await _document(org, samples.mixed_pdf(1, 1))
    async with get_sessionmaker()() as s:
        first = await ingest_document(s, org, doc_id, None)
    assert first.extraction_status == "PARTIAL"
    async with get_sessionmaker()() as s:
        again = await ingest_document(s, org, doc_id, FakeLLMClient())
    assert again.extraction_status == "PARTIAL"
    assert any("partial" in w for w in again.warnings)


async def test_other_organisation_cannot_ingest() -> None:
    org_a, org_b = await _org("A"), await _org("B")
    doc_id = await _document(org_a, samples.pdf_bytes(["x"]))
    async with get_sessionmaker()() as s:
        with pytest.raises(DocumentNotFoundError):
            await ingest_document(s, org_b, doc_id, None)


class _BadEmbedder(FakeLLMClient):
    def __init__(self, vectors: list[list[float]]) -> None:
        super().__init__()
        self.vectors = vectors

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self.vectors


@pytest.mark.parametrize("vectors", [[], [[0.1] * 10]])
async def test_bad_embeddings_raise(vectors: list[list[float]]) -> None:
    org = await _org()
    doc_id = await _document(org, samples.pdf_bytes(["hello world"]))
    async with get_sessionmaker()() as s:
        with pytest.raises(ValueError):
            await ingest_document(s, org, doc_id, _BadEmbedder(vectors))
