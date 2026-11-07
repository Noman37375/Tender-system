"""Numeric criteria evaluator (PRD 8.2). OWNER: rules agent.

Counting policy (MASTER_PROMPT rule 2): only DOCUMENTED, non-expired items count toward the
threshold. SELF_DECLARED items are used in a recount that can lift the result to PARTIAL at
most. EXPIRED / UNVERIFIED items never count, but they do prove that evidence of the metric
exists (so a zero count is NON_COMPLIANT rather than UNVERIFIED).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.rules.parsing import (
    fiscal_year_end,
    is_currency_unit,
    normalise_currency,
    parse_date,
    parse_number,
    subtract_years,
    years_between,
)
from app.schemas.compliance import ComplianceStatus
from app.schemas.evidence import EvidenceCategory, EvidenceItem, VerificationStatus
from app.schemas.tender import CriterionOp, NumericCriterion


@dataclass
class NumericResult:
    status: ComplianceStatus
    detail: str  # readable arithmetic, e.g. "2 of 3 documented projects >= PKR 50M since 2021"
    counted_codes: list[str] = field(default_factory=list)
    action_required: str | None = None


@dataclass
class _Measure:
    """What a metric handler measured; `_decide` turns it into a status."""

    has_evidence: bool
    documented_value: float
    combined_value: float  # documented + self-declared
    documented_codes: list[str]
    self_codes: list[str]  # self-declared codes that contributed to combined_value
    noun: str  # e.g. "qualifying completed project(s)"
    notes: list[str] = field(default_factory=list)
    early_result: NumericResult | None = None  # e.g. currency mismatch -> UNVERIFIED


_METRIC_ALIASES: dict[str, str] = {
    "annual_turnover": "annual_turnover",
    "turnover": "annual_turnover",
    "average_annual_turnover": "annual_turnover",
    "average_turnover": "annual_turnover",
    "annual_revenue": "annual_turnover",
    "revenue": "annual_turnover",
    "similar_projects": "similar_projects",
    "similar_project": "similar_projects",
    "projects": "similar_projects",
    "completed_projects": "similar_projects",
    "similar_assignments": "similar_projects",
    "years_in_business": "years_in_business",
    "company_age": "years_in_business",
    "years_in_operation": "years_in_business",
    "years_of_operation": "years_in_business",
    "staff_count": "staff_count",
    "staff": "staff_count",
    "employees": "staff_count",
    "personnel": "staff_count",
    "key_staff": "staff_count",
    "staff_strength": "staff_count",
}

_GTE_OPS = (CriterionOp.GTE, CriterionOp.COUNT_GTE)
_EACH_YEAR = re.compile(r"\b(each|every|all)\b|per\s+year|per\s+annum|annually|year[- ]wise")
_BEST_YEAR = re.compile(r"\b(best|highest|any\s+one|any\s+single|any\s+of)\b")


def _key(value: object) -> str:
    return re.sub(r"[\s\-]+", "_", str(value).strip().lower()) if value is not None else ""


def normalise_metric(metric: str) -> str | None:
    return _METRIC_ALIASES.get(_key(metric))


def _fmt(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{round(value, 2):g}"


def _is_documented(item: EvidenceItem) -> bool:
    return item.verification_status == VerificationStatus.DOCUMENTED


def _is_self_declared(item: EvidenceItem) -> bool:
    return item.verification_status == VerificationStatus.SELF_DECLARED


def _meets(actual: float, op: CriterionOp, required: float) -> bool:
    if op in _GTE_OPS:
        return actual >= required
    if op == CriterionOp.LTE:
        return actual <= required
    if op == CriterionOp.EQ:
        return abs(actual - required) < 1e-9
    return actual > 0  # EXISTS


def _required_value(criterion: NumericCriterion) -> float:
    if criterion.op == CriterionOp.EXISTS:
        return max(criterion.value, 1.0) if criterion.value else 1.0
    return criterion.value


# ---------------------------------------------------------------- metric handlers


def _turnover(
    criterion: NumericCriterion, evidence: list[EvidenceItem], ref: date, _rel: set[str] | None
) -> _Measure:
    items = [
        e
        for e in evidence
        if e.category == EvidenceCategory.FINANCIAL
        and normalise_metric(str(e.attributes.get("metric") or "")) == "annual_turnover"
    ]
    measure = _Measure(
        has_evidence=bool(items),
        documented_value=0.0,
        combined_value=0.0,
        documented_codes=[],
        self_codes=[],
        noun="annual turnover",
    )
    window = criterion.window_years
    unit = criterion.unit
    usable: list[tuple[EvidenceItem, int, float]] = []
    for item in items:
        if not (_is_documented(item) or _is_self_declared(item)):
            continue
        year = fiscal_year_end(item.attributes.get("fiscal_year"))
        if year is None:
            parsed = parse_date(item.attributes.get("date"))
            year = parsed.year if parsed else None
        value = parse_number(item.attributes.get("value"))
        if year is None or value is None:
            measure.notes.append(f"{item.evidence_code} ignored (no readable fiscal year/value)")
            continue
        if window and not (ref.year - window <= year <= ref.year):
            measure.notes.append(f"{item.evidence_code} FY{year} outside {window}-year window")
            continue
        if year > ref.year:
            continue
        usable.append((item, year, value))

    if is_currency_unit(unit):
        wanted = normalise_currency(unit)
        mismatched = [
            i.evidence_code
            for i, _, _ in usable
            if normalise_currency(i.attributes.get("currency")) != wanted
        ]
        if mismatched:
            measure.early_result = NumericResult(
                status=ComplianceStatus.UNVERIFIED,
                detail=(
                    f"Turnover evidence not in {wanted} ({', '.join(mismatched)}); "
                    "no currency conversion is applied"
                ),
                action_required=f"Provide turnover in {wanted}",
            )
            return measure

    doc_by_year: dict[int, tuple[float, str]] = {}
    self_by_year: dict[int, tuple[float, str]] = {}
    for item, year, value in usable:
        bucket = doc_by_year if _is_documented(item) else self_by_year
        if year not in bucket or value > bucket[year][0]:
            bucket[year] = (value, item.evidence_code)
    combined_by_year = dict(self_by_year)
    combined_by_year.update(doc_by_year)  # a documented figure wins for its year

    def keep_recent(by_year: dict[int, tuple[float, str]]) -> dict[int, tuple[float, str]]:
        years = sorted(by_year, reverse=True)
        if window:
            years = years[:window]
        return {y: by_year[y] for y in years}

    doc_by_year = keep_recent(doc_by_year)
    combined_by_year = keep_recent(combined_by_year)

    qualifier = (criterion.qualifier or "").lower()
    mode = "average"
    if _EACH_YEAR.search(qualifier):
        mode = "each"
    elif _BEST_YEAR.search(qualifier):
        mode = "best"

    def aggregate(by_year: dict[int, tuple[float, str]]) -> float:
        values = [v for v, _ in by_year.values()]
        if not values:
            return 0.0
        if mode == "best":
            return max(values)
        if mode == "each":
            # a missing year inside the window is a year with no proven turnover
            return 0.0 if window and len(values) < window else min(values)
        divisor = max(len(values), window or len(values))  # missing years count as zero
        return sum(values) / divisor

    measure.documented_value = aggregate(doc_by_year)
    measure.combined_value = aggregate(combined_by_year)
    measure.documented_codes = [c for _, c in doc_by_year.values()]
    measure.self_codes = [c for y, (_, c) in combined_by_year.items() if y not in doc_by_year]
    label = {"average": "average", "each": "lowest-year", "best": "best-year"}[mode]
    years_txt = ", ".join(f"FY{y}" for y in sorted(doc_by_year)) or "none"
    measure.noun = f"{label} annual turnover{f' ({unit})' if unit else ''}"
    measure.notes.insert(0, f"documented fiscal years: {years_txt}")
    return measure


def _similar_projects(
    criterion: NumericCriterion, evidence: list[EvidenceItem], ref: date, rel: set[str] | None
) -> _Measure:
    items = [e for e in evidence if e.category == EvidenceCategory.PROJECT]
    measure = _Measure(
        has_evidence=bool(items),
        documented_value=0.0,
        combined_value=0.0,
        documented_codes=[],
        self_codes=[],
        noun="qualifying completed project(s)",
    )
    window = criterion.window_years
    window_start = subtract_years(ref, window) if window else None
    min_value = criterion.per_item_min_value
    unit = criterion.unit
    unit_currency = normalise_currency(unit) if is_currency_unit(unit) else None
    relevant = (rel or set()) if criterion.qualifier else None
    if criterion.qualifier and rel is None:
        measure.notes.append("qualifier set but no relevant evidence codes supplied")

    for item in items:
        code = item.evidence_code
        if not (_is_documented(item) or _is_self_declared(item)):
            measure.notes.append(f"{code} not counted ({item.verification_status.value})")
            continue
        attrs = item.attributes
        status = str(attrs.get("completion_status") or "").lower()
        if "complet" not in status or re.search(r"\b(in|un|not|non)[\s-]?complet", status):
            measure.notes.append(f"{code} not completed")
            continue
        end = parse_date(attrs.get("end_date"))
        if end is not None and end > ref:
            measure.notes.append(f"{code} ends after the deadline")
            continue
        if window_start is not None and (end is None or end < window_start):
            measure.notes.append(f"{code} end date outside {window}-year window")
            continue
        if min_value is not None:
            value = parse_number(attrs.get("value"))
            if value is None:
                measure.notes.append(f"{code} has no readable value")
                continue
            currency = normalise_currency(attrs.get("currency"))
            if unit_currency and currency and currency != unit_currency:
                measure.notes.append(f"{code} value in {currency}, not {unit_currency}")
                continue
            if value < min_value:
                measure.notes.append(f"{code} value {_fmt(value)} < {_fmt(min_value)}")
                continue
        if relevant is not None and code not in relevant:
            measure.notes.append(f"{code} not relevant to qualifier '{criterion.qualifier}'")
            continue
        (measure.documented_codes if _is_documented(item) else measure.self_codes).append(code)

    measure.documented_value = float(len(measure.documented_codes))
    measure.combined_value = float(len(measure.documented_codes) + len(measure.self_codes))
    if min_value is not None:
        measure.noun += f" with value >= {_fmt(min_value)}{f' {unit}' if unit_currency else ''}"
    if window_start is not None:
        measure.noun += f" completed since {window_start.isoformat()}"
    return measure


_REG_DATE_KEYS = ("date", "registration_date", "incorporation_date", "issue_date")


def _years_in_business(
    criterion: NumericCriterion, evidence: list[EvidenceItem], ref: date, _rel: set[str] | None
) -> _Measure:
    dated: list[tuple[EvidenceItem, date]] = []
    for item in evidence:
        if item.category != EvidenceCategory.COMPANY_REGISTRATION:
            continue
        for key in _REG_DATE_KEYS:
            parsed = parse_date(item.attributes.get(key))
            if parsed is not None:
                dated.append((item, parsed))
                break
    measure = _Measure(
        has_evidence=bool(dated),
        documented_value=0.0,
        combined_value=0.0,
        documented_codes=[],
        self_codes=[],
        noun="years in business",
    )
    docs = sorted((d, i.evidence_code) for i, d in dated if _is_documented(i))
    selfs = sorted((d, i.evidence_code) for i, d in dated if _is_self_declared(i))
    if docs:
        measure.documented_value = max(0.0, years_between(docs[0][0], ref))
        measure.documented_codes = [docs[0][1]]
        measure.notes.append(f"registered {docs[0][0].isoformat()} ({docs[0][1]})")
    combined = sorted(docs + selfs)
    if combined:
        measure.combined_value = max(0.0, years_between(combined[0][0], ref))
        if not docs or combined[0][0] < docs[0][0]:
            measure.self_codes = [combined[0][1]]
    return measure


def _staff_count(
    criterion: NumericCriterion, evidence: list[EvidenceItem], ref: date, rel: set[str] | None
) -> _Measure:
    items = [e for e in evidence if e.category == EvidenceCategory.PERSONNEL]
    measure = _Measure(
        has_evidence=bool(items),
        documented_value=0.0,
        combined_value=0.0,
        documented_codes=[],
        self_codes=[],
        noun="qualifying staff",
    )
    min_years = criterion.per_item_min_value
    relevant = (rel or set()) if criterion.qualifier else None
    for item in items:
        code = item.evidence_code
        if not (_is_documented(item) or _is_self_declared(item)):
            continue
        if min_years is not None:
            years = parse_number(item.attributes.get("years_experience"))
            if years is None or years < min_years:
                measure.notes.append(f"{code} below {_fmt(min_years)} years' experience")
                continue
        if relevant is not None and code not in relevant:
            measure.notes.append(f"{code} role not relevant to '{criterion.qualifier}'")
            continue
        (measure.documented_codes if _is_documented(item) else measure.self_codes).append(code)
    measure.documented_value = float(len(measure.documented_codes))
    measure.combined_value = float(len(measure.documented_codes) + len(measure.self_codes))
    if min_years is not None:
        measure.noun += f" with >= {_fmt(min_years)} years' experience"
    return measure


_Handler = Callable[[NumericCriterion, list[EvidenceItem], date, set[str] | None], _Measure]

_HANDLERS: dict[str, _Handler] = {
    "annual_turnover": _turnover,
    "similar_projects": _similar_projects,
    "years_in_business": _years_in_business,
    "staff_count": _staff_count,
}


# ---------------------------------------------------------------- decision


def _decide(criterion: NumericCriterion, m: _Measure) -> NumericResult:
    if m.early_result is not None:
        return m.early_result
    required = _required_value(criterion)
    op = criterion.op
    notes = f" [{'; '.join(m.notes)}]" if m.notes else ""
    base = (
        f"documented {m.noun}: {_fmt(m.documented_value)} vs required {op.value} {_fmt(required)}"
    )
    if not m.has_evidence:
        return NumericResult(
            status=ComplianceStatus.UNVERIFIED,
            detail=f"No evidence of {m.noun} found{notes}",
            action_required=f"Provide documentary evidence of {m.noun}",
        )
    if _meets(m.documented_value, op, required):
        return NumericResult(
            status=ComplianceStatus.COMPLIANT,
            detail=base + notes,
            counted_codes=list(m.documented_codes),
        )
    if m.self_codes and op in _GTE_OPS and _meets(m.combined_value, op, required):
        codes = ", ".join(m.self_codes)
        return NumericResult(
            status=ComplianceStatus.PARTIAL,
            detail=(f"{base}; with self-declared items: {_fmt(m.combined_value)}{notes}"),
            counted_codes=list(m.documented_codes) + list(m.self_codes),
            action_required=f"Provide documentary proof for: {codes}",
        )
    if op in _GTE_OPS and required > 0 and m.documented_value >= 0.5 * required:
        return NumericResult(
            status=ComplianceStatus.PARTIAL,
            detail=f"{base} (>= 50% of requirement){notes}",
            counted_codes=list(m.documented_codes),
            action_required=(
                f"Shortfall: documented {_fmt(m.documented_value)} of required "
                f"{_fmt(required)} {m.noun}; provide further documented evidence"
            ),
        )
    return NumericResult(
        status=ComplianceStatus.NON_COMPLIANT,
        detail=base + notes,
        counted_codes=list(m.documented_codes),
        action_required=(
            f"Requirement not met: documented {_fmt(m.documented_value)} vs required "
            f"{op.value} {_fmt(required)} {m.noun}"
        ),
    )


def evaluate(
    criterion: NumericCriterion,
    evidence: list[EvidenceItem],  # statuses already run-scoped (EXPIRED applied)
    tender_deadline: date | None,
    relevant_codes: set[str] | None = None,  # LLMMatch.relevant_evidence_codes if qualifier set
) -> NumericResult:
    metric = normalise_metric(criterion.metric)
    handler = _HANDLERS.get(metric) if metric else None
    if handler is None:
        return NumericResult(
            status=ComplianceStatus.UNVERIFIED,
            detail=f"Unsupported numeric metric '{criterion.metric}'; cannot be computed",
            action_required=f"Manual review required for metric '{criterion.metric}'",
        )
    ref = tender_deadline or date.today()
    return _decide(criterion, handler(criterion, evidence, ref, relevant_codes))
