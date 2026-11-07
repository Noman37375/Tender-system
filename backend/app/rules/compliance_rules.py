"""Compliance rules R1-R7 (PRD 8.1). OWNER: rules agent.

Order (first match wins after the R1 pre-step):
R1 drop cited codes not in this run's evidence (warning only) -> R2 nothing cited: UNVERIFIED
-> R3 numeric criterion: computed -> R4 all cited EXPIRED: NON_COMPLIANT -> R5 nothing
DOCUMENTED & non-expired: capped at PARTIAL -> R6 LLM COMPLIANT + HIGH + documented: COMPLIANT
-> R7 LLM status capped at PARTIAL.

Invariant: COMPLIANT only comes from R6 (>= 1 cited DOCUMENTED non-expired item) or from R3
(whose COMPLIANT count uses only DOCUMENTED non-expired items).
"""

from datetime import date

from app.rules.evidence_status import is_expired
from app.rules.numeric_criteria import evaluate
from app.schemas.common import Confidence
from app.schemas.compliance import ComplianceRecord, ComplianceStatus, LLMMatch
from app.schemas.evidence import EvidenceItem, VerificationStatus
from app.schemas.tender import Requirement

DOCUMENTARY_PROOF_ACTION = "Provide documentary proof"


def _dedupe(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _run_scoped(
    evidence_by_code: dict[str, EvidenceItem], tender_deadline: date | None
) -> dict[str, EvidenceItem]:
    """Defensive: re-apply certification expiry against the deadline (statuses should already
    be run-scoped; this never un-expires anything)."""
    out: dict[str, EvidenceItem] = {}
    for code, item in evidence_by_code.items():
        if item.verification_status != VerificationStatus.EXPIRED and is_expired(
            item, tender_deadline, None
        ):
            item = item.model_copy(update={"verification_status": VerificationStatus.EXPIRED})
        out[code] = item
    return out


def _cap_partial(status: ComplianceStatus) -> ComplianceStatus:
    return ComplianceStatus.PARTIAL if status == ComplianceStatus.COMPLIANT else status


def _join(*parts: str | None) -> str | None:
    kept = [p.strip() for p in parts if p and p.strip()]
    return " ".join(kept) if kept else None


def is_valid_documented(item: EvidenceItem) -> bool:
    return item.verification_status == VerificationStatus.DOCUMENTED


def apply_rules(
    match: LLMMatch,
    requirement: Requirement,
    evidence_by_code: dict[str, EvidenceItem],  # this run's evidence, statuses run-scoped
    tender_deadline: date | None,
) -> tuple[ComplianceRecord, list[str]]:
    """Return the final record and warnings (e.g. INVALID_CITATION from R1)."""
    if match.req_code != requirement.req_code:
        raise ValueError(
            f"LLM match for {match.req_code} applied to requirement {requirement.req_code}"
        )
    evidence = _run_scoped(evidence_by_code, tender_deadline)
    warnings: list[str] = []

    # R1 — drop citations that do not exist in this run's evidence.
    cited: list[str] = []
    for code in _dedupe(match.evidence_codes):
        if code in evidence:
            cited.append(code)
        else:
            warnings.append(f"INVALID_CITATION: {code}")
    relevant: set[str] = set()
    for code in _dedupe(match.relevant_evidence_codes):
        if code in evidence:
            relevant.add(code)
        elif f"INVALID_CITATION: {code}" not in warnings:
            warnings.append(f"INVALID_CITATION: {code}")

    def record(
        status: ComplianceStatus,
        rule: str,
        rationale: str,
        codes: list[str],
        gap: str | None,
        action: str | None,
    ) -> tuple[ComplianceRecord, list[str]]:
        if status == ComplianceStatus.COMPLIANT:
            gap, action = None, None
        return (
            ComplianceRecord(
                req_code=requirement.req_code,
                status=status,
                evidence_codes=codes,
                llm_proposed_status=match.proposed_status,
                rule_applied=rule,
                rationale=rationale,
                gap_description=gap,
                action_required=action,
            ),
            warnings,
        )

    # R2 — nothing (valid) cited.
    if not cited:
        return record(
            ComplianceStatus.UNVERIFIED,
            "R2",
            _join("No valid evidence cited.", match.rationale) or "No valid evidence cited.",
            [],
            match.gap_description or "No supporting evidence found in company documents",
            match.action_required or "Provide documentary evidence for this requirement",
        )

    # R3 — numeric criteria are decided by code, never by the LLM.
    if requirement.criterion is not None:
        result = evaluate(
            requirement.criterion,
            list(evidence.values()),
            tender_deadline,
            relevant if requirement.criterion.qualifier else None,
        )
        codes = _dedupe(cited + result.counted_codes)
        return record(
            result.status,
            "R3",
            f"Numeric rule: {result.detail}",
            codes,
            None if result.status == ComplianceStatus.COMPLIANT else result.detail,
            result.action_required or match.action_required,
        )

    items = [evidence[c] for c in cited]
    # R4 — everything cited has expired.
    if all(i.verification_status == VerificationStatus.EXPIRED for i in items):
        return record(
            ComplianceStatus.NON_COMPLIANT,
            "R4",
            _join("All cited evidence has expired.", match.rationale) or "",
            cited,
            match.gap_description or f"Expired evidence: {', '.join(cited)}",
            f"Renew or replace expired evidence: {', '.join(cited)}",
        )

    documented = [i for i in items if is_valid_documented(i)]
    # R5 — no documentary proof among the citations.
    if not documented:
        undocumented = ", ".join(cited)
        return record(
            _cap_partial(match.proposed_status),
            "R5",
            _join(match.rationale, "Cited evidence is not backed by documents.") or "",
            cited,
            match.gap_description or f"No documentary proof ({undocumented})",
            f"{DOCUMENTARY_PROOF_ACTION} for: {undocumented}",
        )

    # R6 — LLM COMPLIANT with HIGH confidence and documentary proof.
    if match.proposed_status == ComplianceStatus.COMPLIANT and match.confidence == Confidence.HIGH:
        return record(ComplianceStatus.COMPLIANT, "R6", match.rationale, cited, None, None)

    # R7 — otherwise: the LLM status, never COMPLIANT.
    status = _cap_partial(match.proposed_status)
    action = match.action_required
    if status == ComplianceStatus.PARTIAL and not action:
        action = "Confirm and strengthen evidence for this requirement"
    return record(
        status,
        "R7",
        match.rationale,
        cited,
        match.gap_description
        or (
            f"LLM confidence {match.confidence.value}; not confirmed as fully compliant"
            if match.proposed_status == ComplianceStatus.COMPLIANT
            else None
        ),
        action,
    )
