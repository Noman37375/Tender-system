from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.schemas.common import SourceRef


class EvidenceCategory(StrEnum):
    COMPANY_REGISTRATION = "COMPANY_REGISTRATION"
    TAX_REGISTRATION = "TAX_REGISTRATION"
    FINANCIAL = "FINANCIAL"
    PROJECT = "PROJECT"
    PERSONNEL = "PERSONNEL"
    CERTIFICATION = "CERTIFICATION"
    CAPABILITY = "CAPABILITY"
    PARTNERSHIP = "PARTNERSHIP"
    OTHER = "OTHER"


# evidence codes: EV-<prefix>-NNN (PRD company_extract step 6)
EVIDENCE_CODE_PREFIX: dict[EvidenceCategory, str] = {
    EvidenceCategory.COMPANY_REGISTRATION: "REG",
    EvidenceCategory.TAX_REGISTRATION: "TAX",
    EvidenceCategory.FINANCIAL: "FIN",
    EvidenceCategory.PROJECT: "PRJ",
    EvidenceCategory.PERSONNEL: "PER",
    EvidenceCategory.CERTIFICATION: "CER",
    EvidenceCategory.CAPABILITY: "CAP",
    EvidenceCategory.PARTNERSHIP: "PTN",
    EvidenceCategory.OTHER: "OTH",
}


class VerificationStatus(StrEnum):
    DOCUMENTED = "DOCUMENTED"
    SELF_DECLARED = "SELF_DECLARED"
    EXPIRED = "EXPIRED"  # run-scoped only: computed against the tender deadline, never stored
    UNVERIFIED = "UNVERIFIED"


class EvidenceItem(BaseModel):
    evidence_code: str  # EV-PRJ-001; "TBD" from the LLM
    category: EvidenceCategory
    description: str
    attributes: dict[str, Any]  # keys per category, PRD 6.1
    source: SourceRef
    verification_status: VerificationStatus


class CompanyEvidence(BaseModel):
    company_name: str | None = None
    items: list[EvidenceItem]
    extraction_warnings: list[str] = []
