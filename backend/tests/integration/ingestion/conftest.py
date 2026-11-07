from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient, Response

from app.config import get_settings
from app.ingestion import ocr
from app.ingestion.validation import DOCX_MIME
from tests.conftest import register

API = "/api/v1"


@pytest.fixture(autouse=True)
def storage_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "files"
    monkeypatch.setattr(get_settings(), "STORAGE_PATH", str(root))
    # Deterministic regardless of whether tesseract is installed on the machine.
    monkeypatch.setattr(ocr, "ocr_available", lambda: False)
    yield root


def stored_files(root: Path) -> list[Path]:
    """Files currently in storage (sync helper: tests are async, pathlib calls block)."""
    return list(root.iterdir()) if root.exists() else []


async def auth(client: AsyncClient, email: str, org: str = "Org A") -> dict[str, str]:
    body = await register(client, email, org=org)
    return {"Authorization": f"Bearer {body['access_token']}"}


async def new_tender(client: AsyncClient, headers: dict[str, str], title: str = "T") -> str:
    resp = await client.post(f"{API}/tenders", json={"title": title}, headers=headers)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["tender"]["id"])


def pdf_file(data: bytes, name: str = "doc.pdf") -> tuple[str, tuple[str, bytes, str]]:
    return ("files", (name, data, "application/pdf"))


def docx_file(data: bytes, name: str = "doc.docx") -> tuple[str, tuple[str, bytes, str]]:
    return ("files", (name, data, DOCX_MIME))


async def upload(
    client: AsyncClient,
    headers: dict[str, str],
    tender_id: str,
    files: list[tuple[str, tuple[str, bytes, str]]],
    kind: str = "TENDER",
    **extra: str,
) -> Response:
    return await client.post(
        f"{API}/tenders/{tender_id}/documents",
        files=files,
        data={"kind": kind, **extra},
        headers=headers,
    )
