"""Request/response models for tenders, documents and the knowledge base (PRD 10.2)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TenderCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=500)


class TenderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    title: str | None
    reference_no: str | None
    procuring_entity: str | None
    submission_deadline: datetime | None
    status: str
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime | None


class TenderResponse(BaseModel):
    tender: TenderOut


class TenderListResponse(BaseModel):
    items: list[TenderOut]
    total: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    tender_id: uuid.UUID | None
    kind: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    extraction_status: str
    addendum_seq: int | None
    evidence_extracted_at: datetime | None
    created_at: datetime


class RunSummaryOut(BaseModel):
    """Latest run on the tender page: the run row (steps live under /runs, PRD 10.3)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tender_id: uuid.UUID
    status: str
    current_node: str | None
    revision_count: int
    tokens_in: int
    tokens_out: int
    cost_usd: float  # numeric(10,4) in the DB; a JSON number for the frontend
    budget_usd: float
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class TenderDetailResponse(BaseModel):
    tender: TenderOut
    documents: list[DocumentOut]
    latest_run: RunSummaryOut | None


class DocumentUploadResponse(BaseModel):
    documents: list[DocumentOut]
    warnings: list[str] = []


class DocumentListResponse(BaseModel):
    items: list[DocumentOut]


class PagePreviewResponse(BaseModel):
    document_id: uuid.UUID
    page_no: int
    page_count: int | None
    text: str
    tables: list[Any]
    ocr_used: bool


class DashboardStatsResponse(BaseModel):
    tenders: int
    awaiting_review: int
    approved: int
