"""DOCX extraction with python-docx (PRD 7.3 ingest step 1, the python-docx option).

DOCX has no fixed pages, so the body (paragraphs and tables, in document order) is cut into
pseudo-pages of about PAGE_CHARS characters at block boundaries. Page numbers in citations for
DOCX sources refer to these pseudo-pages; the page preview endpoint shows the same text.
"""

import io
from dataclasses import dataclass, field
from typing import Any

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.ingestion.pdf_extract import ExtractedPage, ExtractionOutput

PAGE_CHARS = 3000


@dataclass
class _PageBuilder:
    lines: list[str] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    size: int = 0


@dataclass
class DocxExtraction(ExtractionOutput):
    # headings[i] lists the heading-styled lines on pages[i]; the chunker uses them.
    headings: list[list[str]] = field(default_factory=list)


def _is_heading(paragraph: Paragraph) -> bool:
    style = paragraph.style.name if paragraph.style is not None else ""
    return bool(style) and (style.startswith("Heading") or style == "Title")


def _table_rows(table: Table) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    for row in table.rows:
        cells: list[str | None] = []
        for cell in row.cells:
            text = " ".join(cell.text.split())
            cells.append(text or None)
        rows.append(cells)
    return rows


def extract_docx(data: bytes) -> DocxExtraction:
    document = docx.Document(io.BytesIO(data))
    built: list[_PageBuilder] = []
    current = _PageBuilder()

    def flush() -> None:
        nonlocal current
        if current.lines or current.tables:
            built.append(current)
        current = _PageBuilder()

    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            if _is_heading(block):
                current.headings.append(text)
            current.lines.append(text)
            current.size += len(text) + 1
        else:
            rows = _table_rows(block)
            if not any(any(c for c in row) for row in rows):
                continue
            current.tables.append({"rows": rows})
            for row in rows:
                line = " | ".join(c or "" for c in row)
                current.lines.append(line)
                current.size += len(line) + 1
        if current.size >= PAGE_CHARS:
            flush()
    flush()

    if not built:  # an empty document still gets one (empty) page so it can be previewed
        built.append(_PageBuilder())
    pages = [
        ExtractedPage(page_no=i + 1, text="\n".join(b.lines), tables=b.tables)
        for i, b in enumerate(built)
    ]
    return DocxExtraction(pages=pages, headings=[b.headings for b in built])
