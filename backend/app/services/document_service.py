"""Uploads, knowledge base, deletion and page preview (PRD 10.2, S-03, S-04)."""

import asyncio
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Document, DocumentPage, User
from app.db.models.documents import DOCUMENT_KINDS
from app.errors import ApiError
from app.ingestion import storage
from app.ingestion.pipeline import ingest_document
from app.ingestion.validation import UploadRejectedError, validate_upload
from app.repositories.documents import DocumentRepository
from app.repositories.tenders import TenderRepository

MAX_FILES_PER_TENDER = 30
MAX_FILES_PER_REQUEST = 30
TENDER_ONLY_KINDS = ("TENDER", "ADDENDUM")
KB_KINDS = tuple(k for k in DOCUMENT_KINDS if k not in TENDER_ONLY_KINDS)

_STATUS_FOR_CODE = {"FILE_TOO_LARGE": 413, "UNSUPPORTED_FILE_TYPE": 415}


class IncomingFile(Protocol):
    """What the service needs from an upload (FastAPI's UploadFile satisfies it)."""

    @property
    def filename(self) -> str | None: ...

    @property
    def size(self) -> int | None: ...

    async def read(self, size: int = -1) -> bytes: ...


@dataclass
class UploadResult:
    documents: list[Document]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PagePreview:
    document: Document
    page: DocumentPage


def _safe_filename(name: str | None) -> str:
    base = PurePath((name or "").replace("\\", "/")).name.strip()
    return (base or "upload")[:255]


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.documents = DocumentRepository(session)
        self.tenders = TenderRepository(session)

    async def upload_to_tender(
        self,
        user: User,
        tender_id: uuid.UUID,
        files: Sequence[IncomingFile],
        kind: str,
        addendum_seq: int | None,
    ) -> UploadResult:
        org_id = user.organisation_id
        if await self.tenders.get(org_id, tender_id) is None:
            raise ApiError(404, "NOT_FOUND", "Tender not found")
        if kind not in DOCUMENT_KINDS:
            raise ApiError(
                422, "VALIDATION_ERROR", "Unknown document kind", {"allowed": DOCUMENT_KINDS}
            )
        if addendum_seq is not None and kind != "ADDENDUM":
            raise ApiError(422, "VALIDATION_ERROR", "addendum_seq is only allowed for ADDENDUM")
        if addendum_seq is not None and addendum_seq < 1:
            raise ApiError(422, "VALIDATION_ERROR", "addendum_seq must be 1 or more")
        self._check_count(files)
        existing = await self.documents.count_for_tender(org_id, tender_id)
        if existing + len(files) > MAX_FILES_PER_TENDER:
            raise ApiError(
                422,
                "TOO_MANY_FILES",
                f"A tender may have at most {MAX_FILES_PER_TENDER} documents",
                {"existing": existing, "uploaded": len(files)},
            )
        seqs: list[int | None] = [None] * len(files)
        if kind == "ADDENDUM":
            if addendum_seq is not None:
                seqs = [addendum_seq + i for i in range(len(files))]
            else:  # next numbers after the addenda already uploaded, in upload order
                start = await self.documents.max_addendum_seq(org_id, tender_id) + 1
                seqs = [start + i for i in range(len(files))]
        return await self._store_and_ingest(org_id, tender_id, files, kind, seqs)

    async def upload_to_knowledge_base(
        self, user: User, files: Sequence[IncomingFile], kind: str
    ) -> UploadResult:
        if kind not in KB_KINDS:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Kind not allowed for company documents",
                {"allowed": KB_KINDS},
            )
        self._check_count(files)
        return await self._store_and_ingest(
            user.organisation_id, None, files, kind, [None] * len(files)
        )

    async def list_knowledge_base(self, organisation_id: uuid.UUID) -> list[Document]:
        return await self.documents.list_knowledge_base(organisation_id)

    async def get_or_404(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.documents.get(organisation_id, document_id)
        if document is None:
            raise ApiError(404, "NOT_FOUND", "Document not found")
        return document

    async def delete(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None:
        document = await self.get_or_404(organisation_id, document_id)
        key = document.storage_path
        try:
            await self.documents.delete(organisation_id, document_id)
            await self.session.commit()
        except IntegrityError as exc:  # requirements cite it as their source (no cascade)
            await self.session.rollback()
            raise ApiError(
                409,
                "DOCUMENT_IN_USE",
                "Extracted requirements cite this document; it cannot be deleted",
            ) from exc
        await asyncio.to_thread(storage.remove, key)

    async def page_preview(
        self, organisation_id: uuid.UUID, document_id: uuid.UUID, page_no: int
    ) -> PagePreview:
        document = await self.get_or_404(organisation_id, document_id)
        page = await self.documents.get_page(organisation_id, document_id, page_no)
        if page is None:
            raise ApiError(404, "NOT_FOUND", "Page not found")
        return PagePreview(document, page)

    # internals ------------------------------------------------------------------------------

    @staticmethod
    def _check_count(files: Sequence[IncomingFile]) -> None:
        if not files:
            raise ApiError(422, "VALIDATION_ERROR", "No files uploaded")
        if len(files) > MAX_FILES_PER_REQUEST:
            raise ApiError(
                422, "TOO_MANY_FILES", f"At most {MAX_FILES_PER_REQUEST} files per upload"
            )

    async def _store_and_ingest(
        self,
        organisation_id: uuid.UUID,
        tender_id: uuid.UUID | None,
        files: Sequence[IncomingFile],
        kind: str,
        seqs: Sequence[int | None],
    ) -> UploadResult:
        max_bytes = get_settings().MAX_UPLOAD_MB * 1024 * 1024
        stored_keys: list[str] = []
        created: list[Document] = []
        try:
            for upload, seq in zip(files, seqs, strict=True):
                filename = _safe_filename(upload.filename)
                try:
                    if upload.size is not None and upload.size > max_bytes:
                        raise UploadRejectedError(
                            "FILE_TOO_LARGE",
                            f"Files may be at most {get_settings().MAX_UPLOAD_MB} MB",
                        )
                    data = await upload.read(max_bytes + 1)
                    mime = await asyncio.to_thread(validate_upload, data, max_bytes)
                except UploadRejectedError as exc:
                    raise ApiError(
                        _STATUS_FOR_CODE.get(exc.code, 422),
                        exc.code,
                        exc.message,
                        {"filename": filename},
                    ) from exc
                key = await asyncio.to_thread(storage.save, data, mime)
                stored_keys.append(key)
                created.append(
                    await self.documents.create(
                        Document(
                            organisation_id=organisation_id,
                            tender_id=tender_id,
                            kind=kind,
                            filename=filename,
                            mime_type=mime,
                            size_bytes=len(data),
                            sha256=hashlib.sha256(data).hexdigest(),
                            storage_path=key,
                            addendum_seq=seq,
                        )
                    )
                )
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            for key in stored_keys:
                await asyncio.to_thread(storage.remove, key)
            raise

        # Synchronous ingestion for M1; embeddings are filled when a run starts (llm given).
        warnings: list[str] = []
        for document in created:
            result = await ingest_document(self.session, organisation_id, document.id, None)
            warnings.extend(result.warnings)
        for document in created:
            await self.session.refresh(document)
        return UploadResult(created, warnings)
