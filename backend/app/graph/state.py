"""Graph state (PRD 7.1).

Outputs are stored as plain dicts of validated Pydantic models so the checkpointer can serialise
them. Large blobs (page text, chunks) never enter state: nodes load them from the DB by id.
"""

import operator
from typing import Annotated, Any, TypedDict


class TenderState(TypedDict, total=False):
    # identity
    run_id: str
    tender_id: str
    organisation_id: str
    # inputs
    tender_document_ids: list[str]
    company_document_ids: list[str]
    # outputs (dicts of validated Pydantic models)
    tender_requirements: dict[str, Any]  # TenderRequirements (active requirements only)
    company_evidence: dict[str, Any]  # CompanyEvidence (run-scoped statuses, EXPIRED applied)
    compliance_matrix: list[dict[str, Any]]  # list[ComplianceRecord]
    bid_decision: dict[str, Any]  # BidDecision
    solution_design: dict[str, Any]  # SolutionDesign
    tender_forms: list[dict[str, Any]]  # list[TenderForm]
    proposal_sections: dict[str, dict[str, Any]]  # section_key -> ProposalSection
    audit_report: dict[str, Any]  # AuditReport
    # control
    revision_count: int
    sections_to_revise: list[str]
    review_decision: dict[str, Any] | None  # from the human_review interrupt
    # accumulators (parallel-safe)
    missing_information: Annotated[list[dict[str, Any]], operator.add]
    warnings: Annotated[list[str], operator.add]
    errors: Annotated[list[dict[str, Any]], operator.add]
