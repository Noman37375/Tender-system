from datetime import date

from app.rules.evidence_status import effective_status, is_expired, with_effective_status
from app.rules.quote_verify import verify_quote
from app.schemas.evidence import EvidenceCategory, VerificationStatus

from .factories import ev

TODAY = date(2026, 1, 15)
DEADLINE = date(2026, 3, 31)


def test_certificate_expired_before_deadline() -> None:
    item = ev("EV-CER-001", expiry_date="2026-02-28")
    assert effective_status(item, DEADLINE, TODAY) == VerificationStatus.EXPIRED


def test_certificate_expired_before_today() -> None:
    item = ev("EV-CER-001", expiry_date="2025-12-31")
    assert effective_status(item, None, TODAY) == VerificationStatus.EXPIRED


def test_certificate_valid() -> None:
    item = ev("EV-CER-001", expiry_date="2027-01-01")
    assert effective_status(item, DEADLINE, TODAY) == VerificationStatus.DOCUMENTED
    assert with_effective_status(item, DEADLINE, TODAY) is item


def test_same_item_valid_for_one_tender_expired_for_another() -> None:
    item = ev("EV-CER-001", expiry_date="2026-06-30")
    assert effective_status(item, date(2026, 5, 1), TODAY) == VerificationStatus.DOCUMENTED
    assert effective_status(item, date(2026, 9, 1), TODAY) == VerificationStatus.EXPIRED


def test_non_certificate_and_unparseable_expiry_keep_stored_status() -> None:
    proj = ev("EV-PRJ-001", EvidenceCategory.PROJECT, expiry_date="2000-01-01")
    assert effective_status(proj, DEADLINE, TODAY) == VerificationStatus.DOCUMENTED
    cert = ev("EV-CER-002", status=VerificationStatus.SELF_DECLARED, expiry_date="soon")
    assert effective_status(cert, DEADLINE, TODAY) == VerificationStatus.SELF_DECLARED
    no_expiry = ev("EV-CER-003")
    assert not is_expired(no_expiry, DEADLINE, TODAY)


def test_with_effective_status_copies_not_mutates() -> None:
    item = ev("EV-CER-001", expiry_date="2025-01-01")
    copy = with_effective_status(item, DEADLINE, TODAY)
    assert copy.verification_status == VerificationStatus.EXPIRED
    assert item.verification_status == VerificationStatus.DOCUMENTED


def test_stored_expired_is_expired() -> None:
    item = ev("EV-PRJ-009", EvidenceCategory.PROJECT, VerificationStatus.EXPIRED)
    assert is_expired(item, None, None)


def test_verify_quote() -> None:
    page = "Section 3.\nThe bidder shall have   an average annual turnover of PKR 100 million."
    assert verify_quote("average annual turnover of PKR 100 million", page)
    assert verify_quote("The bidder shall have an average annual turnover", page)
    assert verify_quote("the bidder shal have an average anual turnover", page)
    assert not verify_quote("ISO 27001 certification is mandatory", page)
    assert not verify_quote("", page)
    assert not verify_quote("anything", "")
    assert verify_quote("“quoted” – text", 'some "quoted" - text here')
