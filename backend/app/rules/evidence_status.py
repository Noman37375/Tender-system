"""Run-scoped evidence status (PRD company_extract step 3). OWNER: rules agent."""

from datetime import date

from app.rules.parsing import parse_date
from app.schemas.evidence import EvidenceCategory, EvidenceItem, VerificationStatus


def is_expired(item: EvidenceItem, tender_deadline: date | None, today: date | None) -> bool:
    """True if a CERTIFICATION's expiry_date is before today or before the tender deadline."""
    if item.verification_status == VerificationStatus.EXPIRED:
        return True
    if item.category != EvidenceCategory.CERTIFICATION:
        return False
    expiry = parse_date(item.attributes.get("expiry_date"))
    if expiry is None:
        return False
    return any(ref is not None and expiry < ref for ref in (today, tender_deadline))


def effective_status(
    item: EvidenceItem, tender_deadline: date | None, today: date
) -> VerificationStatus:
    """EXPIRED if a CERTIFICATION expiry_date < today or < tender_deadline; else stored status."""
    if is_expired(item, tender_deadline, today):
        return VerificationStatus.EXPIRED
    return item.verification_status


def with_effective_status(
    item: EvidenceItem, tender_deadline: date | None, today: date
) -> EvidenceItem:
    """Copy of `item` carrying its run-scoped status (the stored item is never mutated)."""
    status = effective_status(item, tender_deadline, today)
    if status == item.verification_status:
        return item
    return item.model_copy(update={"verification_status": status})
