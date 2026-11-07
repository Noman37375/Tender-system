"""company_extract per document (PRD 7.3, prompt A.4). OWNER: agents agent.

LLM calls: node="company_extract", schema CompanyEvidence, prompt "company_extract@1", fast
tier; one call per ~12k-token window of the document (one call for short documents).

Code-enforced post-processing (not left to the prompt):
- evidence_code is always "TBD" (codes are assigned at persist time);
- verification_status by document kind: only proof documents (certificate, completion letter,
  audited statement, CV) can yield DOCUMENTED, and only for the category they prove; profile
  claims are SELF_DECLARED; EXPIRED is never stored;
- attributes validated per category (PRD 6.1): missing keys -> None, dates -> ISO, numbers
  parsed, currency normalised, registration/tax numbers stripped (number_present instead);
- quote verification: unverifiable quotes keep the item, add a warning and downgrade
  DOCUMENTED to SELF_DECLARED (an unverified quote cannot be proof).
"""

import re
from datetime import date
from typing import Any

import structlog

from app.agents._common import (
    TEMP_EXTRACT,
    build_windows,
    gather_limited,
    llm_concurrency,
    page_lookup,
)
from app.llm.adapter import LLMClient
from app.prompts.loader import load_prompt, wrap_pages
from app.rules import quote_verify
from app.rules.parsing import normalise_currency, parse_number
from app.schemas.evidence import (
    CompanyEvidence,
    EvidenceCategory,
    EvidenceItem,
    VerificationStatus,
)
from app.schemas.pages import PageText

log = structlog.get_logger(__name__)

NODE = "company_extract"

# Document kind -> evidence categories that document can *prove* (PRD 7.3 step 4).
PROOF_CATEGORIES: dict[str, set[EvidenceCategory]] = {
    "PROJECT_CREDENTIAL": {EvidenceCategory.PROJECT},
    "CV": {EvidenceCategory.PERSONNEL},
    "CERTIFICATION": {
        EvidenceCategory.CERTIFICATION,
        EvidenceCategory.COMPANY_REGISTRATION,
        EvidenceCategory.TAX_REGISTRATION,
        EvidenceCategory.PARTNERSHIP,
    },
    "FINANCIAL_STATEMENT": {EvidenceCategory.FINANCIAL},
}
# COMPANY_PROFILE, OTHER and anything unknown prove nothing -> SELF_DECLARED.

ATTRIBUTE_KEYS: dict[EvidenceCategory, tuple[str, ...]] = {
    EvidenceCategory.PROJECT: (
        "client",
        "title",
        "value",
        "currency",
        "start_date",
        "end_date",
        "sector",
        "technologies",
        "completion_status",
    ),
    EvidenceCategory.FINANCIAL: ("metric", "fiscal_year", "value", "currency", "audited"),
    EvidenceCategory.PERSONNEL: (
        "name",
        "role",
        "years_experience",
        "qualifications",
        "certifications",
    ),
    EvidenceCategory.CERTIFICATION: ("name", "issuer", "issue_date", "expiry_date", "scope"),
    EvidenceCategory.COMPANY_REGISTRATION: ("authority", "number_present", "date"),
    EvidenceCategory.TAX_REGISTRATION: ("authority", "number_present", "date"),
}
_DATE_KEYS = {"start_date", "end_date", "issue_date", "expiry_date", "date"}
_LIST_KEYS = {"technologies", "qualifications", "certifications"}
_NUMBER_KEYS = {"value", "years_experience"}
_BOOL_KEYS = {"audited", "number_present"}
# Keys that would hold an actual registration/tax number: never kept (S-07, PRD 6.1).
_SECRET_NUMBER_KEY = re.compile(
    r"^(number|reg(istration)?_?(no|number)|tax_?(no|number|id)|ntn|strn|cnic|license_?(no|number))$",
    re.IGNORECASE,
)

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}


# ------------------------------------------------------------------ coercion helpers
def _safe_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def to_iso_date(value: Any) -> str | None:
    """ISO YYYY-MM-DD. Month-only -> YYYY-MM-01 (PRD A.4); year-only -> YYYY-01-01.
    Unparseable -> None."""
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", text):
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.fullmatch(r"(\d{4})[-/](\d{1,2})", text):
        return _safe_date(int(m[1]), int(m[2]), 1)
    if m := re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", text):
        # Day-first (Pakistan / international usage).
        return _safe_date(int(m[3]), int(m[2]), int(m[1]))
    if m := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})", text):
        month = _MONTHS.get(m[2].lower())
        return _safe_date(int(m[3]), month, int(m[1])) if month else None
    if m := re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", text):
        month = _MONTHS.get(m[1].lower())
        return _safe_date(int(m[3]), month, int(m[2])) if month else None
    if m := re.fullmatch(r"([A-Za-z]+)\.?,?\s+(\d{4})", text):
        month = _MONTHS.get(m[1].lower())
        return _safe_date(int(m[2]), month, 1) if month else None
    if m := re.fullmatch(r"(\d{4})", text):
        return _safe_date(int(m[1]), 1, 1)
    return None


_CURRENCY_TOKEN = re.compile(
    r"(PKR|Rs\.?|USD|US\$|AED|SAR|EUR|GBP|rupees?|dollars?|\$|€|£)", re.IGNORECASE
)


def currency_in(text: str) -> str | None:
    """Currency code mentioned inside a value string such as "PKR 85,000,000" or "$1.2M"."""
    match = _CURRENCY_TOKEN.search(text)
    return normalise_currency(match.group(1)) if match else None


def _to_bool(value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "audited"}:
        return True
    if text in {"false", "no", "n", "0", "unaudited"}:
        return False
    return None


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    return [part.strip() for part in re.split(r"[,;/]", str(value)) if part.strip()]


def normalise_attributes(
    category: EvidenceCategory, attributes: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Per-category attribute validation (PRD 6.1). Returns (attributes, problems)."""
    problems: list[str] = []
    out: dict[str, Any] = {}
    had_secret = False
    for key, value in attributes.items():
        if _SECRET_NUMBER_KEY.match(key):
            had_secret = had_secret or bool(value)
            continue
        out[key] = value
    for key in ATTRIBUTE_KEYS.get(category, ()):
        out.setdefault(key, None)
    if had_secret and "number_present" in out:
        out["number_present"] = True

    for key in list(out):
        value = out[key]
        if key in _DATE_KEYS and value is not None:
            iso = to_iso_date(value)
            if iso is None:
                problems.append(f"{key} could not be read as a date")
            out[key] = iso
        elif key in _NUMBER_KEYS and value is not None and not isinstance(value, int | float):
            number = parse_number(value)
            if number is None:
                problems.append(f"{key} could not be read as a number")
            if key == "value" and out.get("currency") is None:
                out["currency"] = currency_in(str(value))
            out[key] = number
        elif key in _BOOL_KEYS:
            out[key] = _to_bool(value)
        elif key in _LIST_KEYS:
            out[key] = _to_list(value)
    if out.get("currency") is not None:
        out["currency"] = normalise_currency(out["currency"]) or str(out["currency"]).upper()
    return out, problems


def apply_document_kind(item: EvidenceItem, document_kind: str) -> VerificationStatus:
    """DOCUMENTED only when this document kind proves this category (PRD 7.3 step 4)."""
    status = item.verification_status
    if status == VerificationStatus.UNVERIFIED:
        return status
    proves = PROOF_CATEGORIES.get(document_kind.upper(), set())
    if item.category not in proves:
        return VerificationStatus.SELF_DECLARED
    if item.category == EvidenceCategory.FINANCIAL and item.attributes.get("audited") is False:
        return VerificationStatus.SELF_DECLARED  # proof must be an audited statement
    if status == VerificationStatus.EXPIRED:  # never stored; expiry is computed per run
        return VerificationStatus.DOCUMENTED
    return status


def postprocess(raw: CompanyEvidence, document_kind: str, pages: list[PageText]) -> CompanyEvidence:
    lookup = page_lookup(pages)
    items: list[EvidenceItem] = []
    warnings = list(raw.extraction_warnings)
    for index, item in enumerate(raw.items, start=1):
        attributes, problems = normalise_attributes(item.category, item.attributes)
        fixed = item.model_copy(update={"evidence_code": "TBD", "attributes": attributes})
        status = apply_document_kind(fixed, document_kind)
        page_text = lookup.get((fixed.source.document_id, fixed.source.page))
        if page_text is None or not quote_verify.verify_quote(fixed.source.quote, page_text):
            warnings.append(
                f"Evidence item {index} ({fixed.category.value}, page {fixed.source.page}): "
                "source quote could not be verified."
                + (
                    " Status lowered to SELF_DECLARED."
                    if status == VerificationStatus.DOCUMENTED
                    else ""
                )
            )
            if status == VerificationStatus.DOCUMENTED:
                status = VerificationStatus.SELF_DECLARED
        for problem in problems:
            warnings.append(f"Evidence item {index} ({fixed.category.value}): {problem}.")
        items.append(fixed.model_copy(update={"verification_status": status}))
    return CompanyEvidence(
        company_name=raw.company_name,
        items=items,
        extraction_warnings=list(dict.fromkeys(warnings)),
    )


async def _extract_window(
    llm: LLMClient, document_kind: str, window: list[PageText], run_id: str
) -> CompanyEvidence:
    prompt = load_prompt("company_extract")
    user = prompt.user(
        document_id=window[0].document_id, kind=document_kind, pages=wrap_pages(window)
    )
    return await llm.structured(
        system=prompt.system(),
        user=user,
        schema=CompanyEvidence,
        model_tier="fast",
        run_id=run_id,
        node=NODE,
        prompt_version=prompt.prompt_version,
        temperature=TEMP_EXTRACT,
    )


async def extract_company_document(
    llm: LLMClient, document_kind: str, pages: list[PageText], run_id: str
) -> CompanyEvidence:
    """Items keep evidence_code "TBD" (assigned at persist time). Applies DOCUMENTED vs
    SELF_DECLARED by document kind, ISO dates, attribute validation, quote verification."""
    if not pages:
        return CompanyEvidence(items=[], extraction_warnings=["Document has no extracted pages."])
    windows = build_windows(pages)
    parts = await gather_limited(
        windows, lambda w: _extract_window(llm, document_kind, w, run_id), llm_concurrency()
    )
    raw = CompanyEvidence(
        company_name=next((p.company_name for p in parts if p.company_name), None),
        items=[item for p in parts for item in p.items],
        extraction_warnings=[w for p in parts for w in p.extraction_warnings],
    )
    result = postprocess(raw, document_kind, pages)
    log.info(
        "company_extract.done",
        run_id=run_id,
        document_kind=document_kind,
        windows=len(windows),
        items=len(result.items),
    )
    return result
