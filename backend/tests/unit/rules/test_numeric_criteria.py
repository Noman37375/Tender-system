from datetime import date
from typing import Any

from app.rules.numeric_criteria import evaluate, normalise_metric
from app.schemas.compliance import ComplianceStatus as S
from app.schemas.evidence import EvidenceCategory, EvidenceItem
from app.schemas.evidence import VerificationStatus as V
from app.schemas.tender import CriterionOp, NumericCriterion

from .factories import crit, ev, project, turnover

DEADLINE = date(2026, 3, 31)


# ------------------------------------------------------------------ annual turnover


def test_turnover_average_compliant() -> None:
    items = [turnover(f"EV-FIN-00{i}", y, 120_000_000) for i, y in enumerate([2023, 2024, 2025])]
    r = evaluate(crit("annual_turnover", 100e6, unit="PKR", window_years=3), items, DEADLINE)
    assert r.status == S.COMPLIANT
    assert sorted(r.counted_codes) == ["EV-FIN-000", "EV-FIN-001", "EV-FIN-002"]
    assert r.action_required is None


def test_turnover_string_values_and_fiscal_years() -> None:
    items = [
        turnover("EV-FIN-001", "2022-23", "PKR 150M", currency="Rs."),
        turnover("EV-FIN-002", "FY2023-24", "150,000,000"),
        turnover("EV-FIN-003", "2024-25", 150_000_000.0),
    ]
    r = evaluate(crit("turnover", 100e6, unit="PKR", window_years=3), items, DEADLINE)
    assert r.status == S.COMPLIANT


def test_turnover_self_declared_lifts_to_partial_with_codes() -> None:
    items = [
        turnover("EV-FIN-001", 2024, 60_000_000),
        turnover("EV-FIN-002", 2025, 200_000_000, status=V.SELF_DECLARED),
    ]
    r = evaluate(crit("annual_turnover", 100e6, unit="PKR", window_years=2), items, DEADLINE)
    assert r.status == S.PARTIAL
    assert r.action_required == "Provide documentary proof for: EV-FIN-002"
    assert "EV-FIN-002" in r.counted_codes


def test_turnover_fifty_percent_rule() -> None:
    items = [turnover("EV-FIN-001", 2025, 60_000_000)]
    r = evaluate(crit("annual_turnover", 100e6, unit="PKR"), items, DEADLINE)
    assert r.status == S.PARTIAL
    assert r.action_required is not None and "Shortfall" in r.action_required
    low = [turnover("EV-FIN-001", 2025, 40_000_000)]
    r_low = evaluate(crit("annual_turnover", 100e6, unit="PKR"), low, DEADLINE)
    assert r_low.status == S.NON_COMPLIANT


def test_turnover_missing_years_count_as_zero() -> None:
    items = [turnover("EV-FIN-001", 2024, 120e6), turnover("EV-FIN-002", 2025, 120e6)]
    r = evaluate(crit("annual_turnover", 100e6, unit="PKR", window_years=3), items, DEADLINE)
    assert r.status == S.PARTIAL  # (120 + 120 + 0) / 3 = 80M


def test_turnover_outside_window_ignored() -> None:
    items = [turnover("EV-FIN-001", 2018, 900e6), turnover("EV-FIN-002", 2025, 30e6)]
    r = evaluate(crit("annual_turnover", 100e6, unit="PKR", window_years=3), items, DEADLINE)
    assert r.status == S.NON_COMPLIANT
    assert "outside" in r.detail


def test_turnover_keeps_most_recent_years_and_best_value_per_year() -> None:
    items = [
        turnover("EV-FIN-001", 2023, 10e6),
        turnover("EV-FIN-002", 2024, 200e6),
        turnover("EV-FIN-003", 2025, 200e6),
        turnover("EV-FIN-004", 2025, 50e6),
        turnover("EV-FIN-005", 2026, 200e6),
    ]
    r = evaluate(crit("annual_turnover", 150e6, unit="PKR", window_years=3), items, DEADLINE)
    assert r.status == S.COMPLIANT
    assert "EV-FIN-001" not in r.counted_codes
    assert "EV-FIN-004" not in r.counted_codes


def test_turnover_each_year_mode() -> None:
    items = [
        turnover("EV-FIN-001", 2023, 300e6),
        turnover("EV-FIN-002", 2024, 300e6),
        turnover("EV-FIN-003", 2025, 90e6),
    ]
    c = crit("annual_turnover", 100e6, unit="PKR", window_years=3, qualifier="in each year")
    assert evaluate(c, items, DEADLINE).status == S.PARTIAL  # lowest 90M; average would pass
    assert evaluate(c, items[:2], DEADLINE).status == S.NON_COMPLIANT  # missing year is zero


def test_turnover_best_year_mode() -> None:
    items = [turnover("EV-FIN-001", 2024, 10e6), turnover("EV-FIN-002", 2025, 120e6)]
    c = crit("annual_turnover", 100e6, unit="PKR", window_years=3, qualifier="in any one year")
    assert evaluate(c, items, DEADLINE).status == S.COMPLIANT


def test_turnover_currency_mismatch_unverified() -> None:
    items = [turnover("EV-FIN-001", 2025, 5e6, currency="USD")]
    r = evaluate(crit("annual_turnover", 100e6, unit="PKR"), items, DEADLINE)
    assert r.status == S.UNVERIFIED
    assert r.action_required == "Provide turnover in PKR"
    missing = [turnover("EV-FIN-001", 2025, 500e6, currency=None)]
    r2 = evaluate(crit("annual_turnover", 100e6, unit="PKR"), missing, DEADLINE)
    assert r2.status == S.UNVERIFIED


def test_turnover_no_evidence_unverified() -> None:
    other = ev("EV-FIN-009", EvidenceCategory.FINANCIAL, metric="net_worth", value=1e9)
    r = evaluate(crit("annual_turnover", 100e6, unit="PKR"), [other], DEADLINE)
    assert r.status == S.UNVERIFIED
    assert r.counted_codes == []


def test_turnover_only_unusable_items_is_non_compliant() -> None:
    items = [
        turnover("EV-FIN-001", 2025, 500e6, status=V.UNVERIFIED),
        turnover("EV-FIN-002", None, 500e6),
        turnover("EV-FIN-003", 2025, None),
    ]
    r = evaluate(crit("annual_turnover", 100e6, unit="PKR"), items, DEADLINE)
    assert r.status == S.NON_COMPLIANT
    assert "no readable" in r.detail


def test_turnover_year_from_date_attribute_and_no_unit() -> None:
    item = ev(
        "EV-FIN-001",
        EvidenceCategory.FINANCIAL,
        metric="Annual Turnover",
        date="2025-06-30",
        value=200e6,
    )
    assert evaluate(crit("annual_turnover", 100e6), [item], DEADLINE).status == S.COMPLIANT


# ------------------------------------------------------------------ similar projects


def proj_crit(**kw: Any) -> NumericCriterion:
    base: dict[str, Any] = {
        "op": CriterionOp.COUNT_GTE,
        "unit": "projects",
        "window_years": 5,
        "per_item_min_value": 50_000_000,
    }
    base.update(kw)
    return crit("similar_projects", 3, **base)


def test_projects_compliant() -> None:
    items = [project(f"EV-PRJ-00{i}") for i in range(1, 4)]
    r = evaluate(proj_crit(), items, DEADLINE)
    assert r.status == S.COMPLIANT
    assert r.counted_codes == ["EV-PRJ-001", "EV-PRJ-002", "EV-PRJ-003"]


def test_projects_filters() -> None:
    items = [
        project("EV-PRJ-001"),
        project("EV-PRJ-002"),
        project("EV-PRJ-003", value=30_000_000),  # below per-item threshold
        project("EV-PRJ-004", completion_status="ongoing"),
        project("EV-PRJ-005", completion_status="Not completed"),
        project("EV-PRJ-006", end_date="2015-01-01"),  # outside window
        project("EV-PRJ-007", end_date="2027-01-01"),  # after the deadline
        project("EV-PRJ-008", value=None),
        project("EV-PRJ-009", currency="USD"),  # currency mismatch vs PKR unit
        project("EV-PRJ-010", end_date=None),
        project("EV-PRJ-011", status=V.UNVERIFIED),
    ]
    r = evaluate(proj_crit(unit="PKR"), items, DEADLINE)
    assert r.counted_codes == ["EV-PRJ-001", "EV-PRJ-002"]
    assert r.status == S.PARTIAL  # 2 of 3 >= 50 %
    assert "EV-PRJ-003 value 30,000,000 < 50,000,000" in r.detail


def test_projects_self_declared_partial_and_zero_count_non_compliant() -> None:
    items = [
        project("EV-PRJ-001"),
        project("EV-PRJ-002", status=V.SELF_DECLARED),
        project("EV-PRJ-003", status=V.SELF_DECLARED),
    ]
    r = evaluate(proj_crit(), items, DEADLINE)
    assert r.status == S.PARTIAL
    assert r.action_required == "Provide documentary proof for: EV-PRJ-002, EV-PRJ-003"
    zero = evaluate(proj_crit(), [project("EV-PRJ-001", value=1)], DEADLINE)
    assert zero.status == S.NON_COMPLIANT


def test_projects_no_evidence_unverified() -> None:
    assert evaluate(proj_crit(), [ev("EV-CER-001")], DEADLINE).status == S.UNVERIFIED


def test_projects_qualifier_uses_relevant_codes_only() -> None:
    items = [project(f"EV-PRJ-00{i}") for i in range(1, 4)]
    c = proj_crit(qualifier="in government sector")
    all_codes = {"EV-PRJ-001", "EV-PRJ-002", "EV-PRJ-003"}
    assert evaluate(c, items, DEADLINE, all_codes).status == S.COMPLIANT
    assert evaluate(c, items, DEADLINE, {"EV-PRJ-001"}).status == S.NON_COMPLIANT
    r3 = evaluate(c, items, DEADLINE, None)
    assert r3.status == S.NON_COMPLIANT
    assert "no relevant evidence codes" in r3.detail


def test_projects_no_window_no_min_value() -> None:
    items = [project("EV-PRJ-001", value=None, end_date=None)]
    c = crit("similar projects", 1, op=CriterionOp.COUNT_GTE)
    assert evaluate(c, items, DEADLINE).status == S.COMPLIANT


def test_exists_op() -> None:
    c = crit("similar_projects", 0, op=CriterionOp.EXISTS)
    assert evaluate(c, [project("EV-PRJ-001")], DEADLINE).status == S.COMPLIANT
    ongoing = [project("EV-PRJ-001", completion_status="ongoing")]
    assert evaluate(c, ongoing, DEADLINE).status == S.NON_COMPLIANT


# ------------------------------------------------------------------ years in business


def reg(code: str, when: object, status: V = V.DOCUMENTED) -> EvidenceItem:
    return ev(
        code,
        EvidenceCategory.COMPANY_REGISTRATION,
        status,
        authority="SECP",
        number_present=True,
        date=when,
    )


def test_years_in_business() -> None:
    c = crit("years_in_business", 10, unit="years")
    assert evaluate(c, [reg("EV-REG-001", "2015-01-10")], DEADLINE).status == S.COMPLIANT
    assert evaluate(c, [reg("EV-REG-001", "2020-01-10")], DEADLINE).status == S.PARTIAL
    assert evaluate(c, [reg("EV-REG-001", "2024-01-10")], DEADLINE).status == S.NON_COMPLIANT


def test_years_in_business_self_declared_and_missing_date() -> None:
    c = crit("company_age", 10, unit="years")
    items = [reg("EV-REG-001", "2023-01-01"), reg("EV-REG-002", "2010-01-01", V.SELF_DECLARED)]
    r = evaluate(c, items, DEADLINE)
    assert r.status == S.PARTIAL
    assert r.action_required == "Provide documentary proof for: EV-REG-002"
    no_date = ev("EV-REG-001", EvidenceCategory.COMPANY_REGISTRATION, authority="SECP")
    assert evaluate(c, [no_date], DEADLINE).status == S.UNVERIFIED
    only_self = [reg("EV-REG-002", "2023-01-01", V.SELF_DECLARED)]
    assert evaluate(c, only_self, DEADLINE).status == S.NON_COMPLIANT


# ------------------------------------------------------------------ staff count


def staff(code: str, years: object, status: V = V.DOCUMENTED) -> EvidenceItem:
    return ev(
        code, EvidenceCategory.PERSONNEL, status, name="A", role="Engineer", years_experience=years
    )


def test_staff_count() -> None:
    c = crit("staff_count", 2, per_item_min_value=5)
    items = [staff("EV-PER-001", 8), staff("EV-PER-002", "10 years"), staff("EV-PER-003", 2)]
    r = evaluate(c, items, DEADLINE)
    assert r.status == S.COMPLIANT
    assert r.counted_codes == ["EV-PER-001", "EV-PER-002"]
    q = crit("key_staff", 2, qualifier="certified PMs")
    assert evaluate(q, items, DEADLINE, {"EV-PER-003"}).status == S.PARTIAL
    mixed = [
        staff("EV-PER-001", 8),
        staff("EV-PER-002", 8, V.SELF_DECLARED),
        staff("EV-PER-003", 8, V.EXPIRED),
    ]
    r3 = evaluate(crit("staff", 2), mixed, DEADLINE)
    assert r3.status == S.PARTIAL
    assert r3.action_required == "Provide documentary proof for: EV-PER-002"


# ------------------------------------------------------------------ misc


def test_lte_and_eq_ops_have_no_partial() -> None:
    items = [staff("EV-PER-001", 8), staff("EV-PER-002", 8)]

    def status(value: float, op: CriterionOp) -> S:
        return evaluate(crit("staff_count", value, op=op), items, DEADLINE).status

    assert status(3, CriterionOp.LTE) == S.COMPLIANT
    assert status(1, CriterionOp.LTE) == S.NON_COMPLIANT
    assert status(2, CriterionOp.EQ) == S.COMPLIANT
    assert status(4, CriterionOp.EQ) == S.NON_COMPLIANT


def test_unsupported_metric_unverified() -> None:
    r = evaluate(crit("bank_guarantee_capacity", 1), [ev("EV-FIN-001")], DEADLINE)
    assert r.status == S.UNVERIFIED
    assert r.action_required is not None and "Manual review" in r.action_required
    assert normalise_metric("Annual-Turnover") == "annual_turnover"
    assert normalise_metric("??") is None


def test_no_deadline_uses_today() -> None:
    last_year = date.today().replace(year=date.today().year - 1, day=1)
    items = [project("EV-PRJ-001", end_date=last_year)]
    c = crit("similar_projects", 1, op=CriterionOp.COUNT_GTE, window_years=3)
    assert evaluate(c, items, None).status == S.COMPLIANT
