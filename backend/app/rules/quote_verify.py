"""Quote verification (PRD tender_extract step 5). OWNER: rules agent."""

import re

from rapidfuzz import fuzz

_WS = re.compile(r"\s+")


def _normalise(text: str) -> str:
    text = text.replace("­", "")  # soft hyphen from PDF extraction
    text = re.sub(r"[‘’]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[–—]", "-", text)
    return _WS.sub(" ", text).strip().lower()


def verify_quote(quote: str, page_text: str, threshold: int = 85) -> bool:
    """True if `quote` fuzzy-matches (rapidfuzz partial_ratio >= threshold) text on the page."""
    q = _normalise(quote)
    page = _normalise(page_text)
    if not q or not page:
        return False
    if q in page:
        return True
    return fuzz.partial_ratio(q, page) >= threshold
