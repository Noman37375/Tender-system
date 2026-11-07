"""PRD 15 seeded faults: every one must be caught by the deterministic layer.

1. expired certificate          -> compliance R4 NON_COMPLIANT, bid NO_BID, BLOCKER missing item
2. project below value threshold -> not counted by the numeric evaluator
3. fake certification in a draft -> citation checker UNSUPPORTED_CLAIM BLOCKER
4. price in a technical section  -> pricing guard PRICING_LEAK BLOCKER + replaced
"""

from datetime import date

from app.rules.bid_decision import decide, missing_items
from app.rules.citation_checker import deterministic_audit
from app.rules.compliance_rules import apply_rules
from app.rules.evidence_status import with_effective_status
from app.rules.pricing_guard import PRICING_PLACEHOLDER, scan
from app.schemas.audit import FindingType
from app.schemas.compliance import ComplianceStatus as S
from app.schemas.evidence import EvidenceItem
from app.schemas.proposal import Citation, ProposalSection
from app.schemas.tender import CriterionOp, ReqCategory

from .factories import crit, ev, match, project, req

TODAY = date(2026, 1, 10)
DEADLINE = date(2026, 3, 31)


def run_evidence() -> dict[str, EvidenceItem]:
    stored = [
        ev(
            "EV-CER-001",
            description="ISO 27001 certificate",
            name="ISO 27001",
            issuer="SGS",
            issue_date="2023-02-01",
            expiry_date="2026-02-01",  # SEEDED: expires before the tender deadline
        ),
        project("EV-PRJ-001", value=80_000_000),
        project("EV-PRJ-002", value=75_000_000),
        project("EV-PRJ-003", value=30_000_000),  # SEEDED: below the 50M per-project threshold
    ]
    return {i.evidence_code: with_effective_status(i, DEADLINE, TODAY) for i in stored}


def test_seeded_expired_certificate() -> None:
    evidence = run_evidence()
    r = req("CER-001", ReqCategory.CERTIFICATION, description="Valid ISO 27001 certificate")
    m = match(["EV-CER-001"], S.COMPLIANT, req_code="CER-001")
    rec, _ = apply_rules(m, r, evidence, DEADLINE)
    assert rec.status == S.NON_COMPLIANT
    assert rec.rule_applied == "R4"
    decision = decide([r], [rec])
    assert decision.recommendation == "NO_BID"
    assert decision.blocking_req_codes == ["CER-001"]
    assert missing_items([r], [rec])[0].severity == "BLOCKER"


def test_seeded_project_below_value_threshold() -> None:
    evidence = run_evidence()
    r = req(
        "EXP-001",
        ReqCategory.EXPERIENCE,
        description="3 completed projects each >= PKR 50M in the last 5 years",
        criterion=crit(
            "similar_projects",
            3,
            op=CriterionOp.COUNT_GTE,
            unit="PKR",
            window_years=5,
            per_item_min_value=50_000_000,
        ),
    )
    m = match(["EV-PRJ-001", "EV-PRJ-002", "EV-PRJ-003"], S.COMPLIANT, req_code="EXP-001")
    rec, _ = apply_rules(m, r, evidence, DEADLINE)
    assert rec.status != S.COMPLIANT
    assert rec.status == S.PARTIAL  # 2 of 3 qualifying (>= 50 %)
    assert rec.rule_applied == "R3"
    assert "EV-PRJ-003 value 30,000,000 < 50,000,000" in rec.rationale


def test_seeded_fake_certification_in_draft_section() -> None:
    evidence = run_evidence()
    content = (
        "Our organisation is ISO 27001 certified (see Annex). "
        "In addition, we are CMMI Level 3 certified, ensuring mature processes."
    )
    draft = ProposalSection(
        section_key="executive_summary",
        title="Executive Summary",
        content_md=content,
        citations=[Citation(claim="ISO 27001 certified", evidence_codes=["EV-CER-001"])],
        placeholders=[],
    )
    findings = deterministic_audit({"executive_summary": draft}, evidence, [], [], set())
    blockers = [
        f for f in findings if f.type == FindingType.UNSUPPORTED_CLAIM and f.severity == "BLOCKER"
    ]
    assert len(blockers) == 1
    assert "CMMI" in blockers[0].description


def test_seeded_price_in_technical_section() -> None:
    content = (
        "## Architecture\n\nThe solution is deployed on two data centres. "
        "The total price for the hardware is PKR 18,750,000 excluding taxes.\n"
    )
    result = scan("technical_solution", content)
    assert [(f.type, f.severity) for f in result.findings] == [(FindingType.PRICING_LEAK, "BLOCKER")]
    assert "18,750,000" not in result.cleaned_md
    assert PRICING_PLACEHOLDER in result.cleaned_md
    section = ProposalSection(
        section_key="technical_solution",
        title="Proposed Technical Solution",
        content_md=content,
        citations=[],
        placeholders=[],
    )
    audit = deterministic_audit({"technical_solution": section}, {}, [], [], set())
    assert any(f.type == FindingType.PRICING_LEAK for f in audit)
