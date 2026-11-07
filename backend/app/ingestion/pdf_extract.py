"""Per-page PDF extraction (PRD 7.3 ingest steps 2-3): PyMuPDF text, pdfplumber tables, OCR."""

import io
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

from app.ingestion import ocr
from app.ingestion.pdf_open import open_pdf

OCR_CHAR_THRESHOLD = 50


@dataclass
class ExtractedPage:
    page_no: int  # 1-based
    text: str
    tables: list[dict[str, Any]] = field(default_factory=list)
    ocr_used: bool = False

    @property
    def char_count(self) -> int:
        return len(self.text.strip())


@dataclass
class ExtractionOutput:
    pages: list[ExtractedPage]
    warnings: list[str] = field(default_factory=list)


def _clean_cell(cell: Any) -> str | None:
    if cell is None:
        return None
    return " ".join(str(cell).split())


def _tables_for(plumber_page: Any) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for raw in plumber_page.extract_tables() or []:
        rows = [[_clean_cell(c) for c in row] for row in raw if row]
        if any(any(c for c in row) for row in rows):
            tables.append({"rows": rows})
    return tables


def extract_pdf(data: bytes) -> ExtractionOutput:
    """Extract every page. Runs in a worker thread (CPU-bound, blocking)."""
    warnings: list[str] = []
    pages: list[ExtractedPage] = []
    ocr_missing_pages: list[int] = []
    ocr_failed_pages: list[int] = []
    table_failed_pages: list[int] = []

    doc = open_pdf(data)
    try:
        with pdfplumber.open(io.BytesIO(data)) as plumber:
            for index, page in enumerate(doc):
                page_no = index + 1
                text = page.get_text("text")
                try:
                    tables = _tables_for(plumber.pages[index])
                except Exception:  # pdfplumber can fail on odd layouts; text still counts
                    tables = []
                    table_failed_pages.append(page_no)
                extracted = ExtractedPage(page_no=page_no, text=text, tables=tables)

                if extracted.char_count < OCR_CHAR_THRESHOLD and page.get_images(full=False):
                    if not ocr.ocr_available():
                        ocr_missing_pages.append(page_no)
                    else:
                        try:
                            ocr_text = ocr.ocr_page(page)
                        except Exception:
                            ocr_failed_pages.append(page_no)
                        else:
                            if len(ocr_text.strip()) > extracted.char_count:
                                extracted.text = ocr_text
                                extracted.ocr_used = True
                pages.append(extracted)
    finally:
        doc.close()

    if ocr_missing_pages:
        warnings.append(
            f"OCR unavailable; image-only pages left unread: {_pages(ocr_missing_pages)}"
        )
    if ocr_failed_pages:
        warnings.append(f"OCR failed on pages: {_pages(ocr_failed_pages)}")
    if table_failed_pages:
        warnings.append(f"Table extraction failed on pages: {_pages(table_failed_pages)}")
    return ExtractionOutput(pages=pages, warnings=warnings)


def _pages(numbers: list[int]) -> str:
    return ", ".join(str(n) for n in numbers)
