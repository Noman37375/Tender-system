"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-07 14:55:54.369398
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "organisations",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("jurisdiction", sa.Text(), server_default="PK", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organisations")),
    )
    op.create_table(
        "users",
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin','bid_manager','technical_lead','viewer')", name=op.f("ck_users_role")
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_users_organisation_id_organisations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_organisation_id"), "users", ["organisation_id"], unique=False)
    op.create_table(
        "tenders",
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("reference_no", sa.Text(), nullable=True),
        sa.Column("procuring_entity", sa.Text(), nullable=True),
        sa.Column("submission_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), server_default="DRAFT", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT','PROCESSING','AWAITING_REVIEW','CHANGES_REQUESTED','APPROVED','FAILED')",
            name=op.f("ck_tenders_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_tenders_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_tenders_organisation_id_organisations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenders")),
    )
    op.create_index(
        op.f("ix_tenders_organisation_id"), "tenders", ["organisation_id"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("tender_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("extraction_status", sa.Text(), server_default="PENDING", nullable=False),
        sa.Column("addendum_seq", sa.Integer(), nullable=True),
        sa.Column("evidence_extracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "extraction_status IN ('PENDING','DONE','PARTIAL','FAILED')",
            name=op.f("ck_documents_extraction"),
        ),
        sa.CheckConstraint(
            "kind IN ('TENDER','ADDENDUM','COMPANY_PROFILE','PROJECT_CREDENTIAL','CV','CERTIFICATION','FINANCIAL_STATEMENT','OTHER')",
            name=op.f("ck_documents_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_documents_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"], name=op.f("fk_documents_tender_id_tenders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(
        op.f("ix_documents_organisation_id"), "documents", ["organisation_id"], unique=False
    )
    op.create_index(op.f("ix_documents_tender_id"), "documents", ["tender_id"], unique=False)
    op.create_table(
        "runs",
        sa.Column("tender_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("current_node", sa.Text(), nullable=True),
        sa.Column("revision_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(precision=10, scale=4), server_default="0", nullable=False
        ),
        sa.Column(
            "budget_usd", sa.Numeric(precision=10, scale=4), server_default="5.00", nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','WAITING_REVIEW','COMPLETED','FAILED','CANCELLED')",
            name=op.f("ck_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_runs_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"], ["tenders.id"], name=op.f("fk_runs_tender_id_tenders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
        sa.UniqueConstraint("thread_id", name=op.f("uq_runs_thread_id")),
    )
    op.create_index(op.f("ix_runs_organisation_id"), "runs", ["organisation_id"], unique=False)
    op.create_index(op.f("ix_runs_tender_id"), "runs", ["tender_id"], unique=False)
    op.create_table(
        "agent_steps",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=True),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=4), server_default="0", nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('RUNNING','COMPLETED','FAILED','SKIPPED')",
            name=op.f("ck_agent_steps_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_agent_steps_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_agent_steps_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_steps")),
        sa.UniqueConstraint(
            "run_id", "node", "revision", "attempt", name=op.f("uq_agent_steps_run_id")
        ),
    )
    op.create_index(
        op.f("ix_agent_steps_organisation_id"), "agent_steps", ["organisation_id"], unique=False
    )
    op.create_table(
        "bid_decisions",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("eligibility_passed", sa.Boolean(), nullable=False),
        sa.Column(
            "blocking_requirements",
            postgresql.ARRAY(sa.UUID()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "recommendation IN ('BID','BID_WITH_CONDITIONS','NO_BID')",
            name=op.f("ck_bid_decisions_recommendation"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_bid_decisions_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_bid_decisions_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bid_decisions")),
        sa.UniqueConstraint("run_id", name=op.f("uq_bid_decisions_run_id")),
    )
    op.create_index(
        op.f("ix_bid_decisions_organisation_id"), "bid_decisions", ["organisation_id"], unique=False
    )
    op.create_table(
        "chunks",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("section_heading", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_chunks_organisation_id_organisations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
    )
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_chunks_org_document", "chunks", ["organisation_id", "document_id"], unique=False
    )
    op.create_index(op.f("ix_chunks_organisation_id"), "chunks", ["organisation_id"], unique=False)
    op.create_table(
        "document_pages",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "tables", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("ocr_used", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_pages_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_document_pages_organisation_id_organisations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
        sa.UniqueConstraint("document_id", "page_no", name=op.f("uq_document_pages_document_id")),
    )
    op.create_index(
        op.f("ix_document_pages_organisation_id"),
        "document_pages",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "evidence_items",
        sa.Column("evidence_code", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("source_document_id", sa.UUID(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "verification_status IN ('DOCUMENTED','SELF_DECLARED','UNVERIFIED')",
            name=op.f("ck_evidence_items_verification"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_evidence_items_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_evidence_items_source_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_items")),
        sa.UniqueConstraint(
            "organisation_id", "evidence_code", name=op.f("uq_evidence_items_organisation_id")
        ),
    )
    op.create_index(
        op.f("ix_evidence_items_organisation_id"),
        "evidence_items",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "proposals",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('DRAFT','AUDIT_PASSED','AUDIT_FAILED','APPROVED')",
            name=op.f("ck_proposals_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_proposals_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_proposals_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposals")),
        sa.UniqueConstraint("run_id", "version", name=op.f("uq_proposals_run_id")),
    )
    op.create_index(
        op.f("ix_proposals_organisation_id"), "proposals", ["organisation_id"], unique=False
    )
    op.create_table(
        "requirements",
        sa.Column("tender_id", sa.UUID(), nullable=False),
        sa.Column("req_code", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("criterion", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("superseded_by", sa.UUID(), nullable=True),
        sa.Column("extraction_confidence", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "extraction_confidence IN ('HIGH','MEDIUM','LOW')",
            name=op.f("ck_requirements_confidence"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_requirements_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["documents.id"],
            name=op.f("fk_requirements_source_document_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"],
            ["requirements.id"],
            name=op.f("fk_requirements_superseded_by_requirements"),
        ),
        sa.ForeignKeyConstraint(
            ["tender_id"],
            ["tenders.id"],
            name=op.f("fk_requirements_tender_id_tenders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requirements")),
        sa.UniqueConstraint("tender_id", "req_code", name=op.f("uq_requirements_tender_id")),
    )
    op.create_index(
        op.f("ix_requirements_organisation_id"), "requirements", ["organisation_id"], unique=False
    )
    op.create_table(
        "review_actions",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "action IN ('APPROVE','REQUEST_CHANGES','EDIT_SECTION','REGENERATE_SECTION')",
            name=op.f("ck_review_actions_action"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_review_actions_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_review_actions_run_id_runs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_review_actions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_review_actions")),
    )
    op.create_index(
        op.f("ix_review_actions_organisation_id"),
        "review_actions",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("node", sa.Text(), nullable=True),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_run_events_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_run_events_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_events")),
    )
    op.create_index(
        op.f("ix_run_events_organisation_id"), "run_events", ["organisation_id"], unique=False
    )
    op.create_index("ix_run_events_run_id_id", "run_events", ["run_id", "id"], unique=False)
    op.create_table(
        "tender_forms",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("form_code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("envelope", sa.Text(), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fill_status", sa.Text(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "envelope IN ('TECHNICAL','FINANCIAL','ELIGIBILITY')",
            name=op.f("ck_tender_forms_envelope"),
        ),
        sa.CheckConstraint(
            "fill_status IN ('FILLED','PARTIAL','EMPTY','SKIPPED_FINANCIAL')",
            name=op.f("ck_tender_forms_fill_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_tender_forms_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_tender_forms_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tender_forms")),
    )
    op.create_index(
        op.f("ix_tender_forms_organisation_id"), "tender_forms", ["organisation_id"], unique=False
    )
    op.create_table(
        "audit_reports",
        sa.Column("proposal_id", sa.UUID(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("findings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("citation_check", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_audit_reports_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
            name=op.f("fk_audit_reports_proposal_id_proposals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_reports")),
    )
    op.create_index(
        op.f("ix_audit_reports_organisation_id"), "audit_reports", ["organisation_id"], unique=False
    )
    op.create_table(
        "compliance_records",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("requirement_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("evidence_ids", postgresql.ARRAY(sa.UUID()), server_default="{}", nullable=False),
        sa.Column("llm_proposed_status", sa.Text(), nullable=True),
        sa.Column("rule_applied", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("gap_description", sa.Text(), nullable=True),
        sa.Column("action_required", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('COMPLIANT','PARTIAL','NON_COMPLIANT','UNVERIFIED')",
            name=op.f("ck_compliance_records_status"),
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_compliance_records_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"],
            ["requirements.id"],
            name=op.f("fk_compliance_records_requirement_id_requirements"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_compliance_records_run_id_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compliance_records")),
    )
    op.create_index(
        op.f("ix_compliance_records_organisation_id"),
        "compliance_records",
        ["organisation_id"],
        unique=False,
    )
    op.create_table(
        "missing_items",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("item", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("related_requirement_id", sa.UUID(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "severity IN ('BLOCKER','HIGH','MEDIUM','LOW')", name=op.f("ck_missing_items_severity")
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_missing_items_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["related_requirement_id"],
            ["requirements.id"],
            name=op.f("fk_missing_items_related_requirement_id_requirements"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_missing_items_run_id_runs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_missing_items")),
    )
    op.create_index(
        op.f("ix_missing_items_organisation_id"), "missing_items", ["organisation_id"], unique=False
    )
    op.create_table(
        "proposal_sections",
        sa.Column("proposal_id", sa.UUID(), nullable=False),
        sa.Column("section_key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "placeholders",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("edited_by_user", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("organisation_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_proposal_sections_organisation_id_organisations"),
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
            name=op.f("fk_proposal_sections_proposal_id_proposals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_sections")),
        sa.UniqueConstraint(
            "proposal_id", "section_key", name=op.f("uq_proposal_sections_proposal_id")
        ),
    )
    op.create_index(
        op.f("ix_proposal_sections_organisation_id"),
        "proposal_sections",
        ["organisation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_proposal_sections_organisation_id"), table_name="proposal_sections")
    op.drop_table("proposal_sections")
    op.drop_index(op.f("ix_missing_items_organisation_id"), table_name="missing_items")
    op.drop_table("missing_items")
    op.drop_index(op.f("ix_compliance_records_organisation_id"), table_name="compliance_records")
    op.drop_table("compliance_records")
    op.drop_index(op.f("ix_audit_reports_organisation_id"), table_name="audit_reports")
    op.drop_table("audit_reports")
    op.drop_index(op.f("ix_tender_forms_organisation_id"), table_name="tender_forms")
    op.drop_table("tender_forms")
    op.drop_index("ix_run_events_run_id_id", table_name="run_events")
    op.drop_index(op.f("ix_run_events_organisation_id"), table_name="run_events")
    op.drop_table("run_events")
    op.drop_index(op.f("ix_review_actions_organisation_id"), table_name="review_actions")
    op.drop_table("review_actions")
    op.drop_index(op.f("ix_requirements_organisation_id"), table_name="requirements")
    op.drop_table("requirements")
    op.drop_index(op.f("ix_proposals_organisation_id"), table_name="proposals")
    op.drop_table("proposals")
    op.drop_index(op.f("ix_evidence_items_organisation_id"), table_name="evidence_items")
    op.drop_table("evidence_items")
    op.drop_index(op.f("ix_document_pages_organisation_id"), table_name="document_pages")
    op.drop_table("document_pages")
    op.drop_index(op.f("ix_chunks_organisation_id"), table_name="chunks")
    op.drop_index("ix_chunks_org_document", table_name="chunks")
    op.drop_index(
        "ix_chunks_embedding_hnsw",
        table_name="chunks",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("chunks")
    op.drop_index(op.f("ix_bid_decisions_organisation_id"), table_name="bid_decisions")
    op.drop_table("bid_decisions")
    op.drop_index(op.f("ix_agent_steps_organisation_id"), table_name="agent_steps")
    op.drop_table("agent_steps")
    op.drop_index(op.f("ix_runs_tender_id"), table_name="runs")
    op.drop_index(op.f("ix_runs_organisation_id"), table_name="runs")
    op.drop_table("runs")
    op.drop_index(op.f("ix_documents_tender_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_organisation_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_tenders_organisation_id"), table_name="tenders")
    op.drop_table("tenders")
    op.drop_index(op.f("ix_users_organisation_id"), table_name="users")
    op.drop_table("users")
    op.drop_table("organisations")
