import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScoped, Timestamps, UUIDPk, check_in

TENDER_STATUSES = [
    "DRAFT",
    "PROCESSING",
    "AWAITING_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "FAILED",
]
DOCUMENT_KINDS = [
    "TENDER",
    "ADDENDUM",
    "COMPANY_PROFILE",
    "PROJECT_CREDENTIAL",
    "CV",
    "CERTIFICATION",
    "FINANCIAL_STATEMENT",
    "OTHER",
]
EXTRACTION_STATUSES = ["PENDING", "DONE", "PARTIAL", "FAILED"]
EMBEDDING_DIM = 1536  # fixed by migration; startup check lands with embeddings in M1


class Tender(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "tenders"
    __table_args__ = (CheckConstraint(check_in("status", TENDER_STATUSES), name="status"),)

    title: Mapped[str | None] = mapped_column(Text)
    reference_no: Mapped[str | None] = mapped_column(Text)
    procuring_entity: Mapped[str | None] = mapped_column(Text)
    submission_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="DRAFT")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Document(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(check_in("kind", DOCUMENT_KINDS), name="kind"),
        CheckConstraint(check_in("extraction_status", EXTRACTION_STATUSES), name="extraction"),
    )

    # NULL tender_id = company knowledge-base document
    tender_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenders.id"), index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extraction_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="PENDING")
    addendum_seq: Mapped[int | None] = mapped_column(Integer)
    evidence_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentPage(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_no"),)

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    tables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    ocr_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)


class Chunk(UUIDPk, Timestamps, OrgScoped, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_org_document", "organisation_id", "document_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    section_heading: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
