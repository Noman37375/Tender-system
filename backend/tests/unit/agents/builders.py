"""Small factories for agent tests (no DB, no network)."""

from typing import Any

from app.schemas.common import Confidence, SourceRef
from app.schemas.evidence import EvidenceCategory, EvidenceItem, VerificationStatus
from app.schemas.pages import PageText
from app.schemas.tender import ReqCategory, Requirement

DOC = "doc-tender"


def page(no: int, text: str, doc: str = DOC) -> PageText:
    return PageText(document_id=doc, page_no=no, text=text)


def src(quote: str, page_no: int = 1, doc: str = DOC) -> dict[str, Any]:
    return {"document_id": doc, "page": page_no, "quote": quote}


def req_dict(
    description: str,
    category: str = "ELIGIBILITY",
    *,
    page_no: int = 1,
    quote: str | None = None,
    mandatory: bool = True,
    confidence: str = "HIGH",
    code: str = "TBD",
    doc: str = DOC,
    criterion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "req_code": code,
        "category": category,
        "description": description,
        "is_mandatory": mandatory,
        "criterion": criterion,
        "source": src(quote if quote is not None else description, page_no, doc),
        "confidence": confidence,
    }


def req(
    code: str,
    description: str,
    category: ReqCategory = ReqCategory.TECHNICAL,
    mandatory: bool = True,
) -> Requirement:
    return Requirement(
        req_code=code,
        category=category,
        description=description,
        is_mandatory=mandatory,
        source=SourceRef(document_id=DOC, page=1, quote=description[:100]),
        confidence=Confidence.HIGH,
    )


def ev(
    code: str,
    category: EvidenceCategory,
    description: str,
    status: VerificationStatus = VerificationStatus.DOCUMENTED,
    attributes: dict[str, Any] | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_code=code,
        category=category,
        description=description,
        attributes=attributes or {},
        source=SourceRef(document_id="doc-company", page=1, quote=description[:100]),
        verification_status=status,
    )


def tender_answer(
    requirements: list[dict[str, Any]],
    *,
    title: str | None = None,
    warnings: list[str] | None = None,
    structure: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "metadata": {"title": title, "scope_summary": "Supply of an HR system", "sources": []},
        "requirements": requirements,
        "evaluation_criteria": [],
        "prescribed_structure": structure or [],
        "extraction_warnings": warnings or [],
    }
