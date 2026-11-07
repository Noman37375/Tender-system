from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Confidence


class ComplianceStatus(StrEnum):
    COMPLIANT = "COMPLIANT"
    PARTIAL = "PARTIAL"
    NON_COMPLIANT = "NON_COMPLIANT"
    UNVERIFIED = "UNVERIFIED"


class LLMMatch(BaseModel):
    """What the LLM proposes for one requirement (prompt A.5)."""

    req_code: str
    proposed_status: ComplianceStatus
    confidence: Confidence  # used by rules R6/R7
    evidence_codes: list[str]
    relevant_evidence_codes: list[str] = []  # PROJECT codes matching the qualifier (PRD 8.2)
    rationale: str
    gap_description: str | None = None
    action_required: str | None = None


class LLMMatchBatch(BaseModel):
    matches: list[LLMMatch]


class ComplianceRecord(BaseModel):
    """Final status after the rules engine (PRD 8.1)."""

    req_code: str
    status: ComplianceStatus
    evidence_codes: list[str]
    llm_proposed_status: ComplianceStatus
    rule_applied: str  # R2..R7
    rationale: str
    gap_description: str | None = None
    action_required: str | None = None


class MissingInfo(BaseModel):
    item: str
    reason: str
    req_code: str | None = None
    severity: Literal["BLOCKER", "HIGH", "MEDIUM", "LOW"]


class BidDecision(BaseModel):
    recommendation: Literal["BID", "BID_WITH_CONDITIONS", "NO_BID"]
    eligibility_passed: bool
    blocking_req_codes: list[str]
    reasons: list[str]
    score: float | None = None
