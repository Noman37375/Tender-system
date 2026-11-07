"""Bid decision rules (PRD 7.3 bid_decision). OWNER: rules agent."""

from typing import Literal

from app.schemas.compliance import BidDecision, ComplianceRecord, ComplianceStatus, MissingInfo
from app.schemas.tender import ReqCategory, Requirement

ELIGIBILITY_CATEGORIES = frozenset(
    {
        ReqCategory.ELIGIBILITY,
        ReqCategory.FINANCIAL,
        ReqCategory.EXPERIENCE,
        ReqCategory.CERTIFICATION,
        ReqCategory.PERSONNEL,
    }
)
_UNMET = (ComplianceStatus.NON_COMPLIANT, ComplianceStatus.UNVERIFIED)

Severity = Literal["BLOCKER", "HIGH", "MEDIUM", "LOW"]


def _pair(
    requirements: list[Requirement], records: list[ComplianceRecord]
) -> list[tuple[Requirement, ComplianceRecord]]:
    by_code: dict[str, ComplianceRecord] = {}
    for rec in records:
        if rec.req_code in by_code:
            raise ValueError(f"Duplicate compliance record for {rec.req_code}")
        by_code[rec.req_code] = rec
    pairs: list[tuple[Requirement, ComplianceRecord]] = []
    for req in requirements:
        found = by_code.get(req.req_code)
        if found is None:
            raise ValueError(f"Requirement {req.req_code} has no compliance record")
        pairs.append((req, found))
    return pairs


def decide(requirements: list[Requirement], records: list[ComplianceRecord]) -> BidDecision:
    """Rule-based recommendation; `reasons` are plain rule-generated sentences."""
    pairs = _pair(requirements, records)
    mandatory = [(q, r) for q, r in pairs if q.is_mandatory]

    eligibility_failures = [
        q.req_code
        for q, r in mandatory
        if q.category in ELIGIBILITY_CATEGORIES and r.status != ComplianceStatus.COMPLIANT
    ]
    non_compliant = [q.req_code for q, r in mandatory if r.status == ComplianceStatus.NON_COMPLIANT]
    partial = [q.req_code for q, r in mandatory if r.status == ComplianceStatus.PARTIAL]
    unverified = [q.req_code for q, r in mandatory if r.status == ComplianceStatus.UNVERIFIED]
    blocking = [q.req_code for q, r in mandatory if r.status in _UNMET]

    reasons: list[str] = []
    recommendation: Literal["BID", "BID_WITH_CONDITIONS", "NO_BID"]
    if non_compliant:
        recommendation = "NO_BID"
        reasons.append(
            f"{len(non_compliant)} mandatory requirement(s) are not met: "
            f"{', '.join(non_compliant)}."
        )
    elif partial or unverified:
        recommendation = "BID_WITH_CONDITIONS"
    else:
        recommendation = "BID"
        reasons.append(
            f"All {len(mandatory)} mandatory requirement(s) are compliant with documented evidence."
        )
    if unverified:
        reasons.append(
            f"{len(unverified)} mandatory requirement(s) have no verified evidence: "
            f"{', '.join(unverified)}."
        )
    if partial:
        reasons.append(
            f"{len(partial)} mandatory requirement(s) are only partially evidenced: "
            f"{', '.join(partial)}."
        )
    if eligibility_failures:
        reasons.append(
            "Eligibility not yet passed; mandatory eligibility-type requirement(s) not "
            f"compliant: {', '.join(eligibility_failures)}."
        )
    else:
        reasons.append("All mandatory eligibility-type requirements are compliant.")
    optional_gaps = [
        q.req_code
        for q, r in pairs
        if not q.is_mandatory and r.status != ComplianceStatus.COMPLIANT
    ]
    if optional_gaps:
        reasons.append(
            f"{len(optional_gaps)} non-mandatory requirement(s) are not fully compliant."
        )

    return BidDecision(
        recommendation=recommendation,
        eligibility_passed=not eligibility_failures,
        blocking_req_codes=blocking,
        reasons=reasons,
        score=None,  # evaluation-criteria marks are not an input of this function
    )


def severity_for(requirement: Requirement, status: ComplianceStatus) -> Severity:
    if requirement.is_mandatory and status in _UNMET:
        return "BLOCKER"
    if requirement.is_mandatory and status == ComplianceStatus.PARTIAL:
        return "HIGH"
    if status in _UNMET:
        return "MEDIUM"
    return "LOW"


def missing_items(
    requirements: list[Requirement], records: list[ComplianceRecord]
) -> list[MissingInfo]:
    """One item per non-COMPLIANT requirement; BLOCKER if mandatory and NON_COMPLIANT/UNVERIFIED."""
    items: list[MissingInfo] = []
    for req, rec in _pair(requirements, records):
        if rec.status == ComplianceStatus.COMPLIANT:
            continue
        item = rec.action_required or f"Evidence for {req.req_code}: {req.description}"
        reason = rec.gap_description or rec.rationale or f"Status {rec.status.value}"
        items.append(
            MissingInfo(
                item=item,
                reason=f"{rec.status.value}: {reason}",
                req_code=req.req_code,
                severity=severity_for(req, rec.status),
            )
        )
    return items
