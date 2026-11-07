import pytest

from app.rules.bid_decision import decide, missing_items, severity_for
from app.schemas.compliance import ComplianceStatus as S
from app.schemas.tender import ReqCategory

from .factories import record, req


def test_bid_when_all_mandatory_compliant() -> None:
    reqs = [req("ELG-001"), req("TEC-001", ReqCategory.TECHNICAL, mandatory=False)]
    recs = [record("ELG-001", S.COMPLIANT), record("TEC-001", S.PARTIAL)]
    d = decide(reqs, recs)
    assert d.recommendation == "BID"
    assert d.eligibility_passed
    assert d.blocking_req_codes == []
    assert any("non-mandatory" in r for r in d.reasons)
    assert d.score is None


def test_no_bid_on_mandatory_non_compliant() -> None:
    reqs = [req("ELG-001"), req("TEC-001", ReqCategory.TECHNICAL), req("FIN-001", ReqCategory.FINANCIAL)]
    recs = [
        record("ELG-001", S.COMPLIANT),
        record("TEC-001", S.NON_COMPLIANT),
        record("FIN-001", S.UNVERIFIED),
    ]
    d = decide(reqs, recs)
    assert d.recommendation == "NO_BID"
    assert d.blocking_req_codes == ["TEC-001", "FIN-001"]
    assert not d.eligibility_passed
    assert any("TEC-001" in r for r in d.reasons)


def test_bid_with_conditions_on_partial_or_unverified() -> None:
    reqs = [req("ELG-001"), req("TEC-001", ReqCategory.TECHNICAL)]
    d = decide(reqs, [record("ELG-001", S.COMPLIANT), record("TEC-001", S.PARTIAL)])
    assert d.recommendation == "BID_WITH_CONDITIONS"
    assert d.eligibility_passed  # TECHNICAL is not an eligibility category
    assert d.blocking_req_codes == []
    d2 = decide(reqs, [record("ELG-001", S.UNVERIFIED), record("TEC-001", S.COMPLIANT)])
    assert d2.recommendation == "BID_WITH_CONDITIONS"
    assert not d2.eligibility_passed
    assert d2.blocking_req_codes == ["ELG-001"]


def test_non_mandatory_non_compliant_does_not_block() -> None:
    reqs = [req("ELG-001"), req("CER-001", ReqCategory.CERTIFICATION, mandatory=False)]
    d = decide(reqs, [record("ELG-001", S.COMPLIANT), record("CER-001", S.NON_COMPLIANT)])
    assert d.recommendation == "BID"
    assert d.eligibility_passed


def test_requirement_without_record_raises() -> None:
    with pytest.raises(ValueError, match="ELG-002"):
        decide([req("ELG-001"), req("ELG-002")], [record("ELG-001", S.COMPLIANT)])
    with pytest.raises(ValueError):
        missing_items([req("ELG-002")], [])


def test_duplicate_records_raise() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        decide([req("ELG-001")], [record("ELG-001", S.COMPLIANT), record("ELG-001", S.PARTIAL)])


def test_missing_items_severity() -> None:
    reqs = [
        req("ELG-001"),
        req("ELG-002"),
        req("ELG-003"),
        req("TEC-001", ReqCategory.TECHNICAL, mandatory=False),
        req("TEC-002", ReqCategory.TECHNICAL, mandatory=False),
        req("TEC-003", ReqCategory.TECHNICAL, mandatory=False),
        req("SUB-001", ReqCategory.SUBMISSION),
    ]
    recs = [
        record("ELG-001", S.NON_COMPLIANT, action="Renew certificate"),
        record("ELG-002", S.UNVERIFIED),
        record("ELG-003", S.PARTIAL),
        record("TEC-001", S.NON_COMPLIANT),
        record("TEC-002", S.PARTIAL),
        record("TEC-003", S.UNVERIFIED),
        record("SUB-001", S.COMPLIANT),
    ]
    items = missing_items(reqs, recs)
    sev = {i.req_code: i.severity for i in items}
    assert sev == {
        "ELG-001": "BLOCKER",
        "ELG-002": "BLOCKER",
        "ELG-003": "HIGH",
        "TEC-001": "MEDIUM",
        "TEC-002": "LOW",
        "TEC-003": "MEDIUM",
    }
    first = items[0]
    assert first.item == "Renew certificate"
    assert first.reason.startswith("NON_COMPLIANT")
    assert items[1].item.startswith("Evidence for ELG-002")


def test_severity_for_compliant_is_low() -> None:
    assert severity_for(req(), S.COMPLIANT) == "LOW"
