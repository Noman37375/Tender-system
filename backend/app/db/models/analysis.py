import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScoped, Timestamps, UUIDPk, check_in

CONFIDENCE = ["HIGH", "MEDIUM", "LOW"]
# EXPIRED is run-scoped and never stored (PRD 2.1, company_extract step 3)
STORED_VERIFICATION = ["DOCUMENTED", "SELF_DECLARED", "UNVERIFIED"]
COMPLIANCE_STATUSES = ["COMPLIANT", "PARTIAL", "NON_COMPLIANT", "UNVERIFIED"]
RECOMMENDATIONS = ["BID", "BID_WITH_CONDITIONS", "NO_BID"]
SEVERITIES = ["BLOCKER", "HIGH", "MEDIUM", "LOW"]


class Requirement(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "requirements"
    __table_args__ = (
        UniqueConstraint("tender_id", "req_code"),
        CheckConstraint(check_in("extraction_confidence", CONFIDENCE), name="confidence"),
    )

    tender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id", ondelete="CASCADE"), nullable=False
    )
    req_code: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    criterion: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id")
    )
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id")
    )
    extraction_confidence: Mapped[str | None] = mapped_column(Text)


class EvidenceItem(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        UniqueConstraint("organisation_id", "evidence_code"),
        CheckConstraint(check_in("verification_status", STORED_VERIFICATION), name="verification"),
    )

    evidence_code: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # deleting a document deletes its evidence (PRD company_extract step 6)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_quote: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(Text, nullable=False)


class ComplianceRecord(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "compliance_records"
    __table_args__ = (CheckConstraint(check_in("status", COMPLIANCE_STATUSES), name="status"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    llm_proposed_status: Mapped[str | None] = mapped_column(Text)
    rule_applied: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    gap_description: Mapped[str | None] = mapped_column(Text)
    action_required: Mapped[str | None] = mapped_column(Text)


class BidDecision(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "bid_decisions"
    __table_args__ = (
        CheckConstraint(check_in("recommendation", RECOMMENDATIONS), name="recommendation"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    blocking_requirements: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class MissingItem(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "missing_items"
    __table_args__ = (CheckConstraint(check_in("severity", SEVERITIES), name="severity"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    item: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    related_requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id")
    )
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
