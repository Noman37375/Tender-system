from enum import StrEnum

from pydantic import BaseModel

from app.schemas.common import Confidence, SourceRef


class ReqCategory(StrEnum):
    ELIGIBILITY = "ELIGIBILITY"
    FINANCIAL = "FINANCIAL"
    EXPERIENCE = "EXPERIENCE"
    PERSONNEL = "PERSONNEL"
    CERTIFICATION = "CERTIFICATION"
    TECHNICAL = "TECHNICAL"
    SUBMISSION = "SUBMISSION"
    DELIVERABLE = "DELIVERABLE"
    EVALUATION = "EVALUATION"
    COMMERCIAL = "COMMERCIAL"


# req_code prefixes (PRD 7.3 tender_extract step 3): ELG-001, TEC-014 ...
REQ_CODE_PREFIX: dict[ReqCategory, str] = {
    ReqCategory.ELIGIBILITY: "ELG",
    ReqCategory.FINANCIAL: "FIN",
    ReqCategory.EXPERIENCE: "EXP",
    ReqCategory.PERSONNEL: "PER",
    ReqCategory.CERTIFICATION: "CER",
    ReqCategory.TECHNICAL: "TEC",
    ReqCategory.SUBMISSION: "SUB",
    ReqCategory.DELIVERABLE: "DEL",
    ReqCategory.EVALUATION: "EVL",
    ReqCategory.COMMERCIAL: "COM",
}


class CriterionOp(StrEnum):
    GTE = ">="
    LTE = "<="
    EQ = "=="
    EXISTS = "exists"
    COUNT_GTE = "count>="


class NumericCriterion(BaseModel):
    metric: str  # annual_turnover | similar_projects | years_in_business | staff_count
    op: CriterionOp
    value: float
    unit: str | None = None
    window_years: int | None = None
    per_item_min_value: float | None = None
    qualifier: str | None = None


class Requirement(BaseModel):
    req_code: str  # "TBD" from the LLM; assigned by the merge step
    category: ReqCategory
    description: str
    is_mandatory: bool
    criterion: NumericCriterion | None = None
    source: SourceRef
    confidence: Confidence


class EvaluationCriterion(BaseModel):
    name: str
    max_marks: float | None = None
    sub_criteria: list[str] = []
    source: SourceRef


class TenderMetadata(BaseModel):
    title: str | None = None
    reference_no: str | None = None
    procuring_entity: str | None = None
    submission_deadline: str | None = None  # ISO 8601 if determinable
    bid_validity_days: int | None = None
    bid_security: str | None = None
    submission_method: str | None = None
    scope_summary: str = ""
    sources: list[SourceRef] = []


class TenderRequirements(BaseModel):
    metadata: TenderMetadata
    requirements: list[Requirement]
    evaluation_criteria: list[EvaluationCriterion] = []
    prescribed_structure: list[str] = []
    extraction_warnings: list[str] = []


class AddendumChanges(BaseModel):
    """Output of addendum_apply.md (PRD A.3)."""

    modified: list[Requirement] = []  # req_code = the existing code being modified
    added: list[Requirement] = []
    deleted_req_codes: list[str] = []
    deletion_sources: list[SourceRef] = []  # quotes proving each deletion
    metadata_changes: dict[str, str | None] = {}
