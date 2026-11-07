"""Request/response models for runs, results, review and exports (PRD 10.3, 10.4)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.audit import AuditReport
from app.schemas.compliance import BidDecision, ComplianceRecord
from app.schemas.evidence import EvidenceItem
from app.schemas.forms import TenderForm
from app.schemas.tender import EvaluationCriterion, Requirement, TenderMetadata


class StartRunRequest(BaseModel):
    company_document_ids: list[uuid.UUID] = Field(default_factory=list)
    use_knowledge_base: bool = True


class StartRunResponse(BaseModel):
    run_id: uuid.UUID
    status: str


class StatusResponse(BaseModel):
    status: str


class ReviewRequest(BaseModel):
    action: Literal["APPROVE", "REQUEST_CHANGES"]
    sections: list[str] | None = None
    notes: str | None = Field(default=None, max_length=5000)


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tender_id: uuid.UUID
    organisation_id: uuid.UUID
    thread_id: str
    status: str
    current_node: str | None
    revision_count: int
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    budget_usd: Decimal
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node: str
    revision: int
    attempt: int
    status: str
    prompt_version: str | None
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: Decimal | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RunDetail(BaseModel):
    run: RunOut
    steps: list[StepOut]


class RequirementOut(Requirement):
    id: uuid.UUID
    active: bool
    superseded_by: uuid.UUID | None


class AnalysisResponse(BaseModel):
    metadata: TenderMetadata
    requirements: list[RequirementOut]
    evaluation_criteria: list[EvaluationCriterion]
    evidence: list[EvidenceItem]
    warnings: list[str]


class ComplianceSummary(BaseModel):
    compliant: int = 0
    partial: int = 0
    non_compliant: int = 0
    unverified: int = 0


class ComplianceResponse(BaseModel):
    records: list[ComplianceRecord]
    summary: ComplianceSummary


class MissingItemOut(BaseModel):
    id: uuid.UUID
    item: str
    reason: str
    req_code: str | None
    severity: str
    resolved: bool


class MissingListResponse(BaseModel):
    items: list[MissingItemOut]


class MissingPatch(BaseModel):
    resolved: bool


class MissingItemResponse(BaseModel):
    item: MissingItemOut


class FormsResponse(BaseModel):
    forms: list[TenderForm]


class ProposalSectionOut(BaseModel):
    section_key: str
    title: str
    order_index: int
    content_md: str
    citations: list[dict[str, Any]]
    placeholders: list[str]
    edited_by_user: bool


class ProposalInfo(BaseModel):
    version: int
    status: str


class ProposalResponse(BaseModel):
    proposal: ProposalInfo
    sections: list[ProposalSectionOut]
    audit_report: AuditReport | None


class SectionPatch(BaseModel):
    content_md: str = Field(max_length=200_000)


class SectionResponse(BaseModel):
    section: ProposalSectionOut


class RegenerateRequest(BaseModel):
    instructions: str | None = Field(default=None, max_length=5000)


__all__ = ["BidDecision"]
