import itertools
from datetime import date

import pytest

from app.rules.compliance_rules import apply_rules
from app.schemas.common import Confidence
from app.schemas.compliance import ComplianceStatus as S
from app.schemas.evidence import EvidenceCategory, EvidenceItem
from app.schemas.evidence import VerificationStatus as V
from app.schemas.tender import CriterionOp, ReqCategory

from .factories import crit, ev, match, project, req

DEADLINE = date(2026, 3, 31)


def evidence(*items: EvidenceItem) -> dict[str, EvidenceItem]:
    return {i.evidence_code: i for i in items}


def test_r1_drops_invalid_codes_and_warns_then_r2() -> None:
    rec, warnings = apply_rules(match(["EV-CER-999"]), req(), {}, DEADLINE)
    assert warnings == ["INVALID_CITATION: EV-CER-999"]
    assert rec.status == S.UNVERIFIED
    assert rec.rule_applied == "R2"
    assert rec.evidence_codes == []
    assert rec.llm_proposed_status == S.COMPLIANT


def test_r1_continues_with_cleaned_list() -> None:
    ev_map = evidence(ev("EV-CER-001", expiry_date="2030-01-01"))
    m = match(["EV-CER-001", "EV-CER-404", "EV-CER-001"], relevant=["EV-PRJ-404", "EV-CER-404"])
    rec, warnings = apply_rules(m, req(), ev_map, DEADLINE)
    assert rec.status == S.COMPLIANT
    assert rec.rule_applied == "R6"
    assert rec.evidence_codes == ["EV-CER-001"]
    assert warnings == ["INVALID_CITATION: EV-CER-404", "INVALID_CITATION: EV-PRJ-404"]


def test_r2_empty_is_unverified_even_if_llm_says_non_compliant() -> None:
    rec, _ = apply_rules(match([], S.NON_COMPLIANT), req(), {}, DEADLINE)
    assert rec.status == S.UNVERIFIED
    assert rec.rule_applied == "R2"
    assert rec.action_required


def test_r3_numeric_overrides_llm() -> None:
    projects = [project(f"EV-PRJ-00{i}") for i in range(1, 4)]
    r = req(
        "EXP-001",
        ReqCategory.EXPERIENCE,
        criterion=crit("similar_projects", 3, op=CriterionOp.COUNT_GTE, per_item_min_value=50e6),
    )
    m = match(["EV-PRJ-001"], S.NON_COMPLIANT, Confidence.LOW, req_code="EXP-001")
    rec, _ = apply_rules(m, r, evidence(*projects), DEADLINE)
    assert rec.status == S.COMPLIANT
    assert rec.rule_applied == "R3"
    assert set(rec.evidence_codes) == {"EV-PRJ-001", "EV-PRJ-002", "EV-PRJ-003"}
    assert rec.gap_description is None and rec.action_required is None
    assert rec.rationale.startswith("Numeric rule:")


def test_r3_numeric_can_deny_llm_compliant() -> None:
    projects = [project("EV-PRJ-001", value=10e6)]
    r = req(
        "EXP-001",
        ReqCategory.EXPERIENCE,
        criterion=crit("similar_projects", 3, op=CriterionOp.COUNT_GTE, per_item_min_value=50e6),
    )
    rec, _ = apply_rules(match(["EV-PRJ-001"], req_code="EXP-001"), r, evidence(*projects), DEADLINE)
    assert rec.status == S.NON_COMPLIANT
    assert rec.rule_applied == "R3"
    assert rec.action_required


def test_r3_qualifier_passes_relevant_codes() -> None:
    projects = [project(f"EV-PRJ-00{i}") for i in range(1, 3)]
    r = req(
        "EXP-002",
        ReqCategory.EXPERIENCE,
        criterion=crit("similar_projects", 2, op=CriterionOp.COUNT_GTE, qualifier="banking"),
    )
    m = match(["EV-PRJ-001"], req_code="EXP-002", relevant=["EV-PRJ-001", "EV-PRJ-002"])
    rec, _ = apply_rules(m, r, evidence(*projects), DEADLINE)
    assert rec.status == S.COMPLIANT
    m2 = match(["EV-PRJ-001"], req_code="EXP-002", relevant=["EV-PRJ-001"])
    rec2, _ = apply_rules(m2, r, evidence(*projects), DEADLINE)
    assert rec2.status == S.PARTIAL


def test_r4_all_expired_non_compliant() -> None:
    ev_map = evidence(ev("EV-CER-001", status=V.EXPIRED), ev("EV-CER-002", status=V.EXPIRED))
    rec, _ = apply_rules(match(["EV-CER-001", "EV-CER-002"]), req(), ev_map, DEADLINE)
    assert rec.status == S.NON_COMPLIANT
    assert rec.rule_applied == "R4"
    assert rec.action_required is not None and "EV-CER-001" in rec.action_required


def test_r4_defensively_applies_deadline_expiry() -> None:
    """Even if the caller forgot to run-scope statuses, a cert expiring before the deadline
    never supports COMPLIANT."""
    ev_map = evidence(ev("EV-CER-001", expiry_date="2026-01-31"))
    rec, _ = apply_rules(match(["EV-CER-001"]), req(), ev_map, DEADLINE)
    assert rec.status == S.NON_COMPLIANT
    assert rec.rule_applied == "R4"


def test_r5_self_declared_capped_partial() -> None:
    ev_map = evidence(ev("EV-CAP-001", EvidenceCategory.CAPABILITY, V.SELF_DECLARED))
    rec, _ = apply_rules(match(["EV-CAP-001"]), req(), ev_map, DEADLINE)
    assert rec.status == S.PARTIAL
    assert rec.rule_applied == "R5"
    assert rec.action_required is not None
    assert rec.action_required.startswith("Provide documentary proof")


def test_r5_mixed_expired_and_self_declared() -> None:
    ev_map = evidence(
        ev("EV-CER-001", status=V.EXPIRED), ev("EV-CAP-001", EvidenceCategory.CAPABILITY, V.UNVERIFIED)
    )
    rec, _ = apply_rules(match(["EV-CER-001", "EV-CAP-001"], S.NON_COMPLIANT), req(), ev_map, DEADLINE)
    assert rec.status == S.NON_COMPLIANT  # cap at PARTIAL never raises a lower status
    assert rec.rule_applied == "R5"


@pytest.mark.parametrize("confidence", [Confidence.MEDIUM, Confidence.LOW])
def test_r7_compliant_without_high_confidence_is_partial(confidence: Confidence) -> None:
    ev_map = evidence(ev("EV-CER-001"))
    rec, _ = apply_rules(match(["EV-CER-001"], confidence=confidence), req(), ev_map, DEADLINE)
    assert rec.status == S.PARTIAL
    assert rec.rule_applied == "R7"
    assert rec.gap_description is not None and rec.action_required is not None


@pytest.mark.parametrize("status", [S.PARTIAL, S.NON_COMPLIANT, S.UNVERIFIED])
def test_r7_keeps_lower_llm_status(status: S) -> None:
    ev_map = evidence(ev("EV-CER-001"))
    rec, _ = apply_rules(match(["EV-CER-001"], status, action="x"), req(), ev_map, DEADLINE)
    assert rec.status == status
    assert rec.rule_applied == "R7"


def test_req_code_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        apply_rules(match([], req_code="TEC-001"), req("ELG-001"), {}, DEADLINE)


def test_stored_evidence_not_mutated() -> None:
    item = ev("EV-CER-001", expiry_date="2026-01-31")
    apply_rules(match(["EV-CER-001"]), req(), {"EV-CER-001": item}, DEADLINE)
    assert item.verification_status == V.DOCUMENTED


# ---------------------------------------------------------------- invariant (PRD 8.1 / AC-06)


_STATUSES = [V.DOCUMENTED, V.SELF_DECLARED, V.EXPIRED, V.UNVERIFIED]


def _pool() -> dict[str, EvidenceItem]:
    return {
        f"EV-CER-{s.value}": ev(f"EV-CER-{s.value}", status=s, expiry_date="2030-01-01")
        for s in _STATUSES
    } | {"EV-CER-LAPSING": ev("EV-CER-LAPSING", expiry_date="2026-02-01")}


def test_invariant_compliant_always_has_documented_non_expired_evidence() -> None:
    pool = _pool()
    codes = [*pool, "EV-CER-GHOST"]
    checked = 0
    for size in range(0, 4):
        for cited in itertools.combinations(codes, size):
            for proposed in S:
                for confidence in Confidence:
                    m = match(list(cited), proposed, confidence)
                    rec, _ = apply_rules(m, req(), pool, DEADLINE)
                    checked += 1
                    if rec.status != S.COMPLIANT:
                        continue
                    assert rec.rule_applied == "R6"
                    assert any(
                        pool[c].verification_status == V.DOCUMENTED and c != "EV-CER-LAPSING"
                        for c in rec.evidence_codes
                    ), (cited, proposed, confidence)
    assert checked > 500


def test_invariant_numeric_compliant_counts_only_documented() -> None:
    criterion = crit("similar_projects", 2, op=CriterionOp.COUNT_GTE)
    r = req("EXP-001", ReqCategory.EXPERIENCE, criterion=criterion)
    for statuses in itertools.product(_STATUSES, repeat=3):
        items = [project(f"EV-PRJ-00{i}", status=s) for i, s in enumerate(statuses)]
        pool = evidence(*items)
        rec, _ = apply_rules(match(list(pool), req_code="EXP-001"), r, pool, DEADLINE)
        documented = sum(s == V.DOCUMENTED for s in statuses)
        assert (rec.status == S.COMPLIANT) == (documented >= 2), statuses
