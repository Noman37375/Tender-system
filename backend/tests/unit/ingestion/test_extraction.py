from pathlib import Path

import pytest

from app.config import get_settings
from app.ingestion import docx_extract, ocr, pdf_extract, storage
from app.ingestion.validation import (
    DOCX_MIME,
    PDF_MIME,
    UploadRejectedError,
    check_docx_safe,
    check_pdf_safe,
    detect_mime,
    validate_upload,
)
from tests.unit.ingestion import samples

# --- validation -------------------------------------------------------------------------------


def test_detect_mime_by_content() -> None:
    assert detect_mime(samples.pdf_bytes(["x"])) == PDF_MIME
    assert detect_mime(samples.docx_bytes([("p", "x")])) == DOCX_MIME


@pytest.mark.parametrize(
    "data",
    [b"plain text pretending to be a pdf", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, b"PK\x03\x04junk"],
)
def test_detect_mime_rejects_other_types(data: bytes) -> None:
    with pytest.raises(UploadRejectedError) as err:
        detect_mime(data)
    assert err.value.code == "UNSUPPORTED_FILE_TYPE"


def test_plain_zip_is_not_docx() -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hello")
    with pytest.raises(UploadRejectedError):
        detect_mime(buf.getvalue())


@pytest.mark.parametrize(
    ("builder", "code"),
    [
        (samples.js_pdf, "UNSAFE_PDF"),
        (samples.embedded_file_pdf, "UNSAFE_PDF"),
        (samples.encrypted_pdf, "ENCRYPTED_PDF"),
    ],
)
def test_unsafe_pdfs_rejected(builder, code: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(UploadRejectedError) as err:
        check_pdf_safe(builder())
    assert err.value.code == code


def test_broken_pdf_rejected() -> None:
    with pytest.raises(UploadRejectedError) as err:
        check_pdf_safe(b"%PDF-1.7\n garbage without structure")
    assert err.value.code == "INVALID_PDF"


def test_docx_with_macro_rejected() -> None:
    check_docx_safe(samples.docx_bytes([("p", "fine")]))
    with pytest.raises(UploadRejectedError) as err:
        check_docx_safe(samples.docx_bytes([("p", "x")], macro=True))
    assert err.value.code == "UNSAFE_DOCX"
    with pytest.raises(UploadRejectedError):
        check_docx_safe(b"not a zip")


def test_validate_upload_size_and_empty() -> None:
    data = samples.pdf_bytes(["x"])
    assert validate_upload(data, len(data)) == PDF_MIME
    with pytest.raises(UploadRejectedError) as err:
        validate_upload(data, len(data) - 1)
    assert err.value.code == "FILE_TOO_LARGE"
    with pytest.raises(UploadRejectedError) as err:
        validate_upload(b"", 100)
    assert err.value.code == "EMPTY_FILE"
    assert validate_upload(samples.docx_bytes([("p", "x")]), 10**7) == DOCX_MIME


# --- PDF extraction ---------------------------------------------------------------------------


def test_pdf_pages_text_and_tables() -> None:
    out = pdf_extract.extract_pdf(
        samples.pdf_bytes(["Page one", "Page two", "Page three"], table_on_page=2)
    )
    assert [p.page_no for p in out.pages] == [1, 2, 3]
    assert "Page two" in out.pages[1].text
    assert out.pages[1].tables == [{"rows": samples.TABLE_ROWS}]
    assert out.pages[0].tables == [] and not out.pages[0].ocr_used


def test_image_page_without_tesseract_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "ocr_available", lambda: False)
    out = pdf_extract.extract_pdf(samples.image_only_pdf(2))
    assert all(p.text.strip() == "" and not p.ocr_used for p in out.pages)
    assert any("OCR unavailable" in w and "1, 2" in w for w in out.warnings)


def test_image_page_ocr_used_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_page", lambda page: "Scanned bid security form text")
    out = pdf_extract.extract_pdf(samples.image_only_pdf(1))
    assert out.pages[0].ocr_used
    assert out.pages[0].text == "Scanned bid security form text"
    assert out.warnings == []


def test_ocr_failure_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(page: object) -> str:
        raise RuntimeError("tesseract crashed")

    monkeypatch.setattr(ocr, "ocr_available", lambda: True)
    monkeypatch.setattr(ocr, "ocr_page", boom)
    out = pdf_extract.extract_pdf(samples.image_only_pdf(1))
    assert not out.pages[0].ocr_used
    assert out.warnings == ["OCR failed on pages: 1"]


def test_table_failure_is_a_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(page: object) -> list[dict[str, object]]:
        raise RuntimeError("layout")

    monkeypatch.setattr(pdf_extract, "_tables_for", boom)
    out = pdf_extract.extract_pdf(samples.pdf_bytes(["a"]))
    assert out.pages[0].text.strip() == "a"
    assert out.warnings == ["Table extraction failed on pages: 1"]


def test_ocr_available_reports_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> None:
        raise OSError("tesseract not found")

    ocr.ocr_available.cache_clear()
    monkeypatch.setattr(ocr.pytesseract, "get_tesseract_version", missing)
    try:
        assert ocr.ocr_available() is False
    finally:
        ocr.ocr_available.cache_clear()
    monkeypatch.setattr(ocr.pytesseract, "get_tesseract_version", lambda: "5.3")
    try:
        assert ocr.ocr_available() is True
    finally:
        ocr.ocr_available.cache_clear()


def test_ocr_page_renders_and_calls_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingestion.pdf_open import open_pdf

    seen: list[object] = []

    def fake_ocr(image: object) -> str:
        seen.append(image)
        return "recognised"

    monkeypatch.setattr(ocr.pytesseract, "image_to_string", fake_ocr)
    doc = open_pdf(samples.image_only_pdf(1))
    try:
        assert ocr.ocr_page(doc[0]) == "recognised"
    finally:
        doc.close()
    assert len(seen) == 1


# --- DOCX extraction --------------------------------------------------------------------------


def test_docx_paragraphs_tables_and_headings() -> None:
    data = samples.docx_bytes(
        [("h1", "Company Profile"), ("p", "We have built 12 campus networks."), ("h2", "Staff")],
        table=[["Name", "Role"], ["A. Khan", "Network Engineer"]],
    )
    out = docx_extract.extract_docx(data)
    assert len(out.pages) == 1
    page = out.pages[0]
    assert "We have built 12 campus networks." in page.text
    assert "A. Khan | Network Engineer" in page.text
    assert page.tables == [{"rows": [["Name", "Role"], ["A. Khan", "Network Engineer"]]}]
    assert out.headings == [["Company Profile", "Staff"]]


def test_docx_split_into_pseudo_pages() -> None:
    blocks = [("p", f"Paragraph {i} " + "x" * 500) for i in range(20)]  # ~10k chars
    out = docx_extract.extract_docx(samples.docx_bytes(blocks))
    assert len(out.pages) >= 3
    assert [p.page_no for p in out.pages] == list(range(1, len(out.pages) + 1))
    assert all(len(p.text) < docx_extract.PAGE_CHARS + 600 for p in out.pages)
    assert "Paragraph 0 " in out.pages[0].text and "Paragraph 19 " in out.pages[-1].text


def test_empty_docx_has_one_empty_page() -> None:
    out = docx_extract.extract_docx(samples.docx_bytes([], table=[["", ""]]))
    assert len(out.pages) == 1 and out.pages[0].text == ""


# --- storage ----------------------------------------------------------------------------------


def test_storage_roundtrip_creates_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "nested" / "files"
    monkeypatch.setattr(get_settings(), "STORAGE_PATH", str(root))
    key = storage.save(b"%PDF-data", PDF_MIME)
    assert key.endswith(".pdf") and len(key) == 36
    assert (root / key).exists()
    assert storage.read(key) == b"%PDF-data"
    storage.remove(key)
    assert not (root / key).exists()
    storage.remove(key)  # missing file is fine
    storage.remove("../../etc/passwd")  # invalid key is ignored
    with pytest.raises(ValueError):
        storage.path_for("../secret.pdf")
