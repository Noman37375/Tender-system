import uuid
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScoped, Timestamps, UUIDPk, check_in

PROPOSAL_STATUSES = ["DRAFT", "AUDIT_PASSED", "AUDIT_FAILED", "APPROVED"]
ENVELOPES = ["TECHNICAL", "FINANCIAL", "ELIGIBILITY"]
FILL_STATUSES = ["FILLED", "PARTIAL", "EMPTY", "SKIPPED_FINANCIAL"]
REVIEW_ACTIONS = ["APPROVE", "REQUEST_CHANGES", "EDIT_SECTION", "REGENERATE_SECTION"]


class Proposal(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "proposals"
    __table_args__ = (
        UniqueConstraint("run_id", "version"),
        CheckConstraint(check_in("status", PROPOSAL_STATUSES), name="status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)


class ProposalSection(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "proposal_sections"
    __table_args__ = (UniqueConstraint("proposal_id", "section_key"),)

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False
    )
    section_key: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    placeholders: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    edited_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class TenderForm(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "tender_forms"
    __table_args__ = (
        CheckConstraint(check_in("envelope", ENVELOPES), name="envelope"),
        CheckConstraint(check_in("fill_status", FILL_STATUSES), name="fill_status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    form_code: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    envelope: Mapped[str] = mapped_column(Text, nullable=False)
    fields: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    fill_status: Mapped[str] = mapped_column(Text, nullable=False)


class AuditReport(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "audit_reports"

    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    findings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    citation_check: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ReviewAction(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "review_actions"
    __table_args__ = (CheckConstraint(check_in("action", REVIEW_ACTIONS), name="action"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
