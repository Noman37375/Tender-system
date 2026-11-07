from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class FindingType(StrEnum):
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    MISSING_MANDATORY_COVERAGE = "MISSING_MANDATORY_COVERAGE"
    MISSING_SECTION = "MISSING_SECTION"
    CONTRADICTION = "CONTRADICTION"
    PRICING_LEAK = "PRICING_LEAK"
    STRUCTURE_DEVIATION = "STRUCTURE_DEVIATION"
    TERMINOLOGY_INCONSISTENCY = "TERMINOLOGY_INCONSISTENCY"
    INVALID_CITATION = "INVALID_CITATION"


class AuditFinding(BaseModel):
    type: FindingType
    severity: Literal["BLOCKER", "MAJOR", "MINOR"]
    section_key: str | None = None
    description: str
    suggested_fix: str


class AuditFindingList(BaseModel):
    findings: list[AuditFinding]


class AuditReport(BaseModel):
    passed: bool  # computed: no BLOCKER and no MAJOR findings
    findings: list[AuditFinding]
    sections_to_revise: list[str]
