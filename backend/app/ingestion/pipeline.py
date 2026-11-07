"""Document ingestion (PRD 7.3 ingest). OWNER: ingestion agent.

`ingest_document` is idempotent per document:
- If the document has not been extracted yet (PENDING/FAILED, or no pages), it reads the stored
  file, extracts pages (PyMuPDF + pdfplumber + OCR fallback, or python-docx), chunks them and
  writes `document_pages` and `chunks`, then commits.
- If `llm` is given, it embeds every chunk of the document whose embedding IS NULL, in batches,
  and commits. Upload calls it with llm=None; a run calls it again with the real client, which
  fills the embeddings without re-extracting.

Extraction errors mark the document FAILED and are reported in the result (never raised), so one
bad file does not fail a batch. Embedding errors propagate: the caller (graph node) retries, and
the retry only embeds chunks still missing a vector.
"""

import asyncio
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document
from app.db.models.documents import EMBEDDING_DIM
from app.ingestion import storage
from app.ingestion.chunker import ChunkDraft, PageInput, chunk_pages
from app.ingestion.docx_extract import DocxExtraction, extract_docx
from app.ingestion.pdf_extract import ExtractionOutput, extract_pdf
from app.ingestion.validation import DOCX_MIME, PDF_MIME
from app.llm.adapter import LLMClient
from app.repositories.documents import DocumentRepository

log = structlog.get_logger(__name__)

EMBED_BATCH = 64
PARTIAL_EMPTY_RATIO = 0.20


@dataclass
class IngestResult:
    document_id: uuid.UUID
    page_count: int
    extraction_status: str  # DONE | PARTIAL | FAILED
    warnings: list[str] = field(default_factory=list)


class DocumentNotFoundError(LookupError):
    pass


def _extract(data: bytes, mime_type: str) -> tuple[ExtractionOutput, list[PageInput]]:
    """Blocking extraction + page inputs for the chunker. Runs in a worker thread."""
    if mime_type == PDF_MIME:
        out: ExtractionOutput = extract_pdf(data)
        inputs = [PageInput(p.page_no, p.text) for p in out.pages]
    elif mime_type == DOCX_MIME:
        docx_out: DocxExtraction = extract_docx(data)
        out = docx_out
        inputs = [
            PageInput(p.page_no, p.text, frozenset(h))
            for p, h in zip(docx_out.pages, docx_out.headings, strict=True)
        ]
    else:
        raise ValueError(f"unsupported mime type {mime_type}")
    return out, inputs


def _extract_and_chunk(data: bytes, mime_type: str) -> tuple[ExtractionOutput, list[ChunkDraft]]:
    out, inputs = _extract(data, mime_type)
    return out, chunk_pages(inputs)


async def _extract_document(
    session: AsyncSession, repo: DocumentRepository, document: Document
) -> IngestResult:
    label = f"Document {document.filename}"
    try:
        data = storage.read(document.storage_path)
        out, chunks = await asyncio.to_thread(_extract_and_chunk, data, document.mime_type)
    except Exception as exc:
        log.warning("ingest.extract_failed", document_id=str(document.id), error=type(exc).__name__)
        document.extraction_status = "FAILED"
        await session.commit()
        return IngestResult(document.id, 0, "FAILED", [f"{label}: extraction failed"])

    warnings = [f"{label}: {w}" for w in out.warnings]
    pages = out.pages
    empty = sum(1 for p in pages if p.char_count == 0 and not p.tables)
    status = "DONE"
    if pages and empty / len(pages) > PARTIAL_EMPTY_RATIO:
        status = "PARTIAL"
        warnings.append(f"{label}: {empty} of {len(pages)} pages have no text after OCR")

    await repo.replace_pages_and_chunks(
        document.organisation_id,
        document.id,
        [
            {
                "page_no": p.page_no,
                "text": p.text,
                "tables": p.tables,
                "ocr_used": p.ocr_used,
                "char_count": p.char_count,
            }
            for p in pages
        ],
        [
            {
                "page_start": c.page_start,
                "page_end": c.page_end,
                "section_heading": c.section_heading,
                "content": c.content,
                "token_count": c.token_count,
            }
            for c in chunks
        ],
    )
    document.page_count = len(pages)
    document.extraction_status = status
    await session.commit()
    return IngestResult(document.id, len(pages), status, warnings)


async def _embed_missing(
    session: AsyncSession, repo: DocumentRepository, document: Document, llm: LLMClient
) -> int:
    pending = await repo.chunks_without_embedding(document.organisation_id, document.id)
    for start in range(0, len(pending), EMBED_BATCH):
        batch = pending[start : start + EMBED_BATCH]
        vectors = await llm.embed([c.content for c in batch])
        if len(vectors) != len(batch):
            raise ValueError("embedding count does not match chunk count")
        for chunk, vector in zip(batch, vectors, strict=True):
            if len(vector) != EMBEDDING_DIM:
                raise ValueError(
                    f"embedding has {len(vector)} dimensions, expected {EMBEDDING_DIM}"
                )
            await repo.set_embedding(document.organisation_id, chunk.id, vector)
        await session.commit()
    return len(pending)


async def ingest_document(
    session: AsyncSession,
    organisation_id: uuid.UUID,
    document_id: uuid.UUID,
    llm: LLMClient | None,
) -> IngestResult:
    repo = DocumentRepository(session)
    document = await repo.get(organisation_id, document_id)
    if document is None:
        raise DocumentNotFoundError(str(document_id))

    already = document.extraction_status in ("DONE", "PARTIAL") and (
        await repo.count_pages(organisation_id, document_id) > 0
    )
    if already:
        result = IngestResult(document.id, document.page_count or 0, document.extraction_status)
        if document.extraction_status == "PARTIAL":
            result.warnings.append(
                f"Document {document.filename}: extraction is partial (many pages without text)"
            )
    else:
        result = await _extract_document(session, repo, document)

    if llm is not None and result.extraction_status != "FAILED":
        await _embed_missing(session, repo, document, llm)
    return result
