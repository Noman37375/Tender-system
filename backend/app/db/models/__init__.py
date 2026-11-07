"""Import every model so Base.metadata is complete (Alembic, tests)."""

from app.db.models.analysis import (
    BidDecision,
    ComplianceRecord,
    EvidenceItem,
    MissingItem,
    Requirement,
)
from app.db.models.documents import Chunk, Document, DocumentPage, Tender
from app.db.models.org import Organisation, User
from app.db.models.proposal import (
    AuditReport,
    Proposal,
    ProposalSection,
    ReviewAction,
    TenderForm,
)
from app.db.models.runs import AgentStep, Run, RunEvent

__all__ = [
    "AgentStep",
    "AuditReport",
    "BidDecision",
    "Chunk",
    "ComplianceRecord",
    "Document",
    "DocumentPage",
    "EvidenceItem",
    "MissingItem",
    "Organisation",
    "Proposal",
    "ProposalSection",
    "Requirement",
    "ReviewAction",
    "Run",
    "RunEvent",
    "Tender",
    "TenderForm",
    "User",
]
