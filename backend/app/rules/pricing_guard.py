"""Pricing guard (PRD 8.4). OWNER: rules agent.

A sentence is a pricing leak when it contains a currency amount (PKR, Rs, USD, $, AED, SAR,
before or after the number) AND a price context word (price, cost, rate, quote, fee, ...).
In `company_profile` / `experience`, sentences about turnover or project/contract values are
allowed. Leaking sentences are replaced by PRICING_PLACEHOLDER and reported as BLOCKERs.
"""

import re
from dataclasses import dataclass, field

from app.schemas.audit import AuditFinding, FindingType
from app.schemas.forms import TenderForm

PRICING_ALLOWED_SECTIONS = {"company_profile", "experience"}  # turnover/project values allowed
PRICING_PLACEHOLDER = "[CLIENT INPUT REQUIRED: commercial content belongs in financial proposal]"

_AMOUNT = r"\d[\d,]*(?:\.\d+)?(?:\s*(?:k|m|mn|million|bn|billion|crores?|cr|lakhs?|lacs?)\b)?"
CURRENCY_AMOUNT_RE = re.compile(
    rf"(?:(?<![A-Za-z])(?:PKR|Rs\.?|USD|US\$|AED|SAR)\s*{_AMOUNT}|\${_AMOUNT}"
    rf"|(?<![\w.])\d[\d,]*(?:\.\d+)?(?:\s*(?:million|billion|m|mn|bn))?\s*(?:PKR|USD|AED|SAR)\b)",
    re.IGNORECASE,
)
_PRICE_CONTEXT_RE = re.compile(
    r"\b(price[sd]?|pricing|costs?|costing|rates?|quot(?:e|es|ed|ation|ations)|fees?"
    r"|charges?|charged|tariffs?|payable|lump[\s-]?sum|discount(?:ed|s)?|bid\s+amount"
    r"|contract\s+price)\b"
    r"|\bper\s+(?:hour|day|month|year|annum|user|seat|licen[cs]e|unit|site|device)\b"
    r"|/\s*(?:hour|hr|day|month|mo|year|yr|user)\b",
    re.IGNORECASE,
)
_ALLOWED_CONTEXT_RE = re.compile(
    r"\b(turnover|revenue|net\s+worth|project|projects|contract|contracts|valued|worth"
    r"|portfolio|completed|delivered|executed)\b",
    re.IGNORECASE,
)
# Sentence terminator: . ! ? followed by whitespace/end, but not the dot of "Rs." / "No." etc.
_TERMINATOR_RE = re.compile(r"(?<!\bRs)(?<!\bNo)(?<!\be\.g)(?<!\bi\.e)(?<!\bvs)[.!?](?=\s|$)")
_LEADING_MARKUP_RE = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)*")


@dataclass
class PricingResult:
    cleaned_md: str
    findings: list[AuditFinding] = field(default_factory=list)


def _sentence_span(line: str, start: int, end: int) -> tuple[int, int]:
    """Bounds of the sentence (or table cell) around line[start:end]."""
    left = 0
    for pos in range(start - 1, -1, -1):
        if line[pos] == "|":
            left = pos + 1
            break
        if _TERMINATOR_RE.match(line, pos) and pos + 1 <= start:
            left = pos + 1
            break
    if left == 0:
        markup = _LEADING_MARKUP_RE.match(line)
        left = markup.end() if markup else 0
    right = len(line)
    for pos in range(end, len(line)):
        if line[pos] == "|":
            right = pos
            break
        if _TERMINATOR_RE.match(line, pos):
            right = pos + 1
            break
    while left < right and line[left].isspace():
        left += 1
    while right > left and line[right - 1].isspace():
        right -= 1
    return left, right


def _is_leak(sentence: str, section_key: str) -> bool:
    if not _PRICE_CONTEXT_RE.search(sentence):
        return False
    if section_key in PRICING_ALLOWED_SECTIONS and _ALLOWED_CONTEXT_RE.search(sentence):
        return False
    return True


def find_leaks(section_key: str, text: str) -> list[str]:
    """The leaking sentences in `text` (no replacement)."""
    return [s for _, _, s in _scan_line_spans(section_key, text)]


def _scan_line_spans(section_key: str, text: str) -> list[tuple[int, int, str]]:
    """(absolute start, absolute end, sentence) for each leaking sentence, non-overlapping."""
    spans: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        line_spans: list[tuple[int, int]] = []
        for m in CURRENCY_AMOUNT_RE.finditer(body):
            left, right = _sentence_span(body, m.start(), m.end())
            if line_spans and left < line_spans[-1][1]:
                continue
            if _is_leak(body[left:right], section_key):
                line_spans.append((left, right))
        spans.extend((offset + a, offset + b, body[a:b]) for a, b in line_spans)
        offset += len(line)
    return spans


def scan(section_key: str, content_md: str) -> PricingResult:
    """Replace price sentences with the placeholder; report PRICING_LEAK BLOCKERs."""
    spans = _scan_line_spans(section_key, content_md)
    cleaned = content_md
    for start, end, _ in reversed(spans):
        cleaned = cleaned[:start] + PRICING_PLACEHOLDER + cleaned[end:]
    findings = [
        AuditFinding(
            type=FindingType.PRICING_LEAK,
            severity="BLOCKER",
            section_key=section_key,
            description=f'Commercial/pricing content in a technical section: "{sentence[:200]}"',
            suggested_fix="Remove pricing; commercial content belongs in the financial proposal.",
        )
        for _, _, sentence in spans
    ]
    return PricingResult(cleaned_md=cleaned, findings=findings)


def scan_form(form: TenderForm) -> list[AuditFinding]:
    """Pricing in a non-financial form's filled values (financial forms are never filled)."""
    if form.envelope == "FINANCIAL":
        return []
    findings: list[AuditFinding] = []
    for fld in form.fields:
        if not fld.value:
            continue
        for sentence in find_leaks(f"form:{form.form_code}", fld.value):
            findings.append(
                AuditFinding(
                    type=FindingType.PRICING_LEAK,
                    severity="BLOCKER",
                    section_key="forms_annex",
                    description=(
                        f"Pricing in form {form.form_code} field '{fld.label}': "
                        f'"{sentence[:200]}"'
                    ),
                    suggested_fix="Clear the value; pricing belongs in the financial proposal.",
                )
            )
    return findings
