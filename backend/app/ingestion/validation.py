"""Upload validation (S-03, PRD 10.2): type by magic bytes, size limit, unsafe PDF content."""

import io
import re
import zipfile

import filetype  # type: ignore[import-untyped]

from app.ingestion.pdf_open import open_pdf

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED_MIME = (PDF_MIME, DOCX_MIME)

# A name token, so "/JSON" or "/JScript" do not match but "/JS (", "/JS<<" and "/JavaScript" do.
_PDF_SCRIPT = re.compile(r"/(JavaScript|JS)(?![A-Za-z0-9])")


class UploadRejectedError(ValueError):
    """The file must not be stored. `code` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def detect_mime(data: bytes) -> str:
    """Return the allowed MIME type of `data`, judged by content only (not by file name)."""
    kind = filetype.guess(data)
    mime = kind.mime if kind is not None else None
    if mime == PDF_MIME:
        return PDF_MIME
    if mime == DOCX_MIME or (mime == "application/zip" and _is_docx_zip(data)):
        return DOCX_MIME
    raise UploadRejectedError(
        "UNSUPPORTED_FILE_TYPE", f"Only PDF and DOCX files are accepted (detected: {mime})"
    )


def _is_docx_zip(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return "word/document.xml" in zf.namelist()
    except zipfile.BadZipFile:
        return False


def check_pdf_safe(data: bytes) -> None:
    """Reject PDFs that are encrypted, unreadable, carry JavaScript or embed files."""
    try:
        doc = open_pdf(data)
    except Exception as exc:  # PyMuPDF raises several types for broken files
        raise UploadRejectedError("INVALID_PDF", "The PDF could not be read") from exc
    try:
        if doc.needs_pass:
            raise UploadRejectedError("ENCRYPTED_PDF", "Password-protected PDFs are not accepted")
        if doc.embfile_count() > 0:
            raise UploadRejectedError("UNSAFE_PDF", "PDFs with embedded files are not accepted")
        for xref in range(1, doc.xref_length()):
            try:
                obj = doc.xref_object(xref, compressed=False)
            except Exception:  # noqa: S112 - a broken object cannot hold a readable script
                continue
            if _PDF_SCRIPT.search(obj):
                raise UploadRejectedError(
                    "UNSAFE_PDF", "PDFs containing JavaScript are not accepted"
                )
        if doc.page_count == 0:
            raise UploadRejectedError("INVALID_PDF", "The PDF has no pages")
    finally:
        doc.close()


def check_docx_safe(data: bytes) -> None:
    """Reject DOCX packages that are not readable or that carry macros (a renamed .docm)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise UploadRejectedError("INVALID_DOCX", "The DOCX file could not be read") from exc
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        raise UploadRejectedError("UNSAFE_DOCX", "DOCX files with macros are not accepted")


def validate_upload(data: bytes, max_bytes: int) -> str:
    """Run every check on one uploaded file; return its MIME type or raise UploadRejectedError."""
    if not data:
        raise UploadRejectedError("EMPTY_FILE", "The file is empty")
    if len(data) > max_bytes:
        raise UploadRejectedError(
            "FILE_TOO_LARGE", f"Files may be at most {max_bytes // (1024 * 1024)} MB"
        )
    mime = detect_mime(data)
    if mime == PDF_MIME:
        check_pdf_safe(data)
    else:
        check_docx_safe(data)
    return mime
