"""Builders for rules/export unit tests (pure objects, no DB)."""

from typing import Any

from app.schemas.common import Confidence, SourceRef
from app.schemas.compliance import ComplianceRecord, ComplianceStatus, LLMMatch
from app.schemas.evidence import EvidenceCategory, EvidenceItem, VerificationStatus
from app.schemas.tender import CriterionOp, NumericCriterion, ReqCategory, Requirement

SRC = SourceRef(document_id="doc-1", page=3, quote="verbatim quote")


def ev(
    code: str,
    category: EvidenceCategory = EvidenceCategory.CERTIFICATION,
    status: VerificationStatus = VerificationStatus.DOCUMENTED,
    description: str = "evidence",
    **attributes: Any,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_code=code,
        category=category,
        description=description,
        attributes=attributes,
        source=SRC,
        verification_status=status,
    )


def project(
    code: str,
    value: Any = 100_000_000,
    end_date: Any = "2024-06-30",
    status: VerificationStatus = VerificationStatus.DOCUMENTED,
    completion_status: Any = "completed",
    currency: Any = "PKR",
    client: str = "Punjab Revenue Authority",
    **extra: Any,
) -> EvidenceItem:
    return ev(
        code,
        EvidenceCategory.PROJECT,
        status,
        description=f"Project for {client}",
        client=client,
        title="ERP implementation",
        value=value,
        currency=currency,
        start_date="2022-01-01",
        end_date=end_date,
        sector="government",
        technologies=["Python"],
        completion_status=completion_status,
        **extra,
    )


def turnover(
    code: str,
    fiscal_year: Any,
    value: Any,
    status: VerificationStatus = VerificationStatus.DOCUMENTED,
    currency: Any = "PKR",
) -> EvidenceItem:
    return ev(
        code,
        EvidenceCategory.FINANCIAL,
        status,
        description="Audited turnover",
        metric="annual_turnover",
        fiscal_year=fiscal_year,
        value=value,
        currency=currency,
        audited=True,
    )


def req(
    code: str = "ELG-001",
    category: ReqCategory = ReqCategory.ELIGIBILITY,
    mandatory: bool = True,
    criterion: NumericCriterion | None = None,
    description: str = "Bidder must hold a valid certificate",
) -> Requirement:
    return Requirement(
        req_code=code,
        category=category,
        description=description,
        is_mandatory=mandatory,
        criterion=criterion,
        source=SRC,
        confidence=Confidence.HIGH,
    )


def crit(
    metric: str,
    value: float,
    op: CriterionOp = CriterionOp.GTE,
    **kw: Any,
) -> NumericCriterion:
    return NumericCriterion(metric=metric, op=op, value=value, **kw)


def match(
    codes: list[str],
    status: ComplianceStatus = ComplianceStatus.COMPLIANT,
    confidence: Confidence = Confidence.HIGH,
    req_code: str = "ELG-001",
    relevant: list[str] | None = None,
    action: str | None = None,
) -> LLMMatch:
    return LLMMatch(
        req_code=req_code,
        proposed_status=status,
        confidence=confidence,
        evidence_codes=codes,
        relevant_evidence_codes=relevant or [],
        rationale="LLM rationale",
        gap_description=None,
        action_required=action,
    )


def record(
    code: str, status: ComplianceStatus, action: str | None = None, codes: list[str] | None = None
) -> ComplianceRecord:
    return ComplianceRecord(
        req_code=code,
        status=status,
        evidence_codes=codes or [],
        llm_proposed_status=status,
        rule_applied="R7",
        rationale="because",
        gap_description=None if status == ComplianceStatus.COMPLIANT else "gap",
        action_required=action,
    )
