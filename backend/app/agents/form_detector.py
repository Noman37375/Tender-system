"""form_detection two passes (PRD 7.3, prompt A.7). OWNER: agents agent.

LLM calls (node="form_detection", schema TenderFormList, fast tier):
- pass 1 (prompt "form_extract@1:detect"): one call per ~12k-token window of the candidate
  pages — pages whose text has form headings (Form, Schedule, Annex, Affidavit, ...) plus the
  page after each. No candidate pages -> no LLM call and no forms.
- pass 2 (prompt "form_extract@1:fill"): one call with the detected forms and the evidence
  register; skipped when pass 1 found no forms.

Code enforces (not just the prompt):
- structure (forms, envelope, field labels) comes from pass 1; pass 2 only supplies values;
- forms whose title looks financial (price schedule, BOQ, financial bid ...) are FINANCIAL;
- FINANCIAL forms: every value None, NEEDS_INPUT (graph stores fill_status SKIPPED_FINANCIAL);
- signature / stamp / signing date / witness / declaration fields: None, NEEDS_INPUT;
- FILLED only with a value AND at least one evidence code that exists in the register.
"""

import re

import structlog

from app.agents._common import (
    TEMP_EXTRACT,
    build_windows,
    evidence_view,
    gather_limited,
    llm_concurrency,
)
from app.llm.adapter import LLMClient
from app.prompts.loader import load_prompt, wrap_data, wrap_pages
from app.schemas.evidence import EvidenceItem
from app.schemas.forms import FormField, TenderForm, TenderFormList
from app.schemas.pages import PageText

log = structlog.get_logger(__name__)

NODE = "form_detection"

FORM_HEADING = re.compile(
    r"\b(form|schedule|annex(ure)?|appendix|proforma|pro-forma|affidavit|undertaking"
    r"|declaration|cv\s+format|curriculum\s+vitae\s+format|bid\s+form|template)\b",
    re.IGNORECASE,
)
FINANCIAL_TITLE = re.compile(
    r"\b(financial\s+(bid|proposal|offer|form)|price\s+(schedule|bid|form|proposal)"
    r"|bill\s+of\s+quantit|boq|price\s+breakdown|cost\s+breakdown|rate\s+schedule"
    r"|schedule\s+of\s+(prices|rates))",
    re.IGNORECASE,
)
SENSITIVE_LABEL = re.compile(
    r"\bsign|stamp|\bseal\b|witness|declar|undertak|affirm|attest|\boath\b|thumb|accept"
    r"|^\s*date\s*:?\s*$|\bdated\b|\bplace\s+and\s+date\b",
    re.IGNORECASE,
)

DETECT_TASK = """PASS 1 – DETECT.
Tender pages {page_start}–{page_end} of document {document_id}:

{pages}"""

FILL_TASK = """PASS 2 – FILL.
Detected forms (from pass 1):
{forms}

Evidence register:
{evidence}"""


def candidate_pages(pages: list[PageText]) -> list[PageText]:
    """Pages with a form-like heading, plus the following page (forms often span two)."""
    selected: set[int] = set()
    for i, page in enumerate(pages):
        head = "\n".join(page.text.splitlines()[:15])
        if FORM_HEADING.search(head):
            selected.add(i)
            if i + 1 < len(pages) and pages[i + 1].document_id == page.document_id:
                selected.add(i + 1)
    return [pages[i] for i in sorted(selected)]


def is_sensitive(label: str) -> bool:
    return bool(SENSITIVE_LABEL.search(label))


def enforce_rules(form: TenderForm, evidence_codes: set[str]) -> TenderForm:
    envelope = "FINANCIAL" if _is_financial(form) else form.envelope
    fields: list[FormField] = []
    for fld in form.fields:
        if envelope == "FINANCIAL" or is_sensitive(fld.label):
            fields.append(FormField(label=fld.label, value=None, status="NEEDS_INPUT"))
            continue
        if fld.status == "NOT_APPLICABLE":
            fields.append(FormField(label=fld.label, value=None, status="NOT_APPLICABLE"))
            continue
        codes = [c for c in dict.fromkeys(fld.evidence_codes) if c in evidence_codes]
        value = fld.value.strip() if fld.value else None
        if value and codes:
            fields.append(
                FormField(label=fld.label, value=value, evidence_codes=codes, status="FILLED")
            )
        else:
            fields.append(FormField(label=fld.label, value=None, status="NEEDS_INPUT"))
    return form.model_copy(update={"envelope": envelope, "fields": fields})


def _is_financial(form: TenderForm) -> bool:
    return (
        form.envelope == "FINANCIAL"
        or bool(FINANCIAL_TITLE.search(form.title))
        or bool(FINANCIAL_TITLE.search(form.form_code))
    )


def _blank(form: TenderForm) -> TenderForm:
    """Pass-1 form with empty fields and the envelope corrected for financial titles."""
    return form.model_copy(
        update={
            "envelope": "FINANCIAL" if _is_financial(form) else form.envelope,
            "fields": [
                FormField(label=f.label, value=None, status="NEEDS_INPUT") for f in form.fields
            ],
        }
    )


def _merge_fill(detected: TenderForm, filled: TenderForm | None) -> TenderForm:
    """Pass-1 structure, pass-2 values matched by field label."""
    if filled is None:
        return detected
    by_label = {f.label.strip().lower(): f for f in filled.fields}
    fields = []
    for fld in detected.fields:
        match = by_label.get(fld.label.strip().lower())
        fields.append(match.model_copy(update={"label": fld.label}) if match else fld)
    return detected.model_copy(update={"fields": fields})


async def _detect(llm: LLMClient, window: list[PageText], run_id: str) -> list[TenderForm]:
    prompt = load_prompt("form_extract")
    task = DETECT_TASK.format(
        page_start=window[0].page_no,
        page_end=window[-1].page_no,
        document_id=window[0].document_id,
        pages=wrap_pages(window),
    )
    result = await llm.structured(
        system=prompt.system(),
        user=prompt.user(task=task),
        schema=TenderFormList,
        model_tier="fast",
        run_id=run_id,
        node=NODE,
        prompt_version=f"{prompt.prompt_version}:detect",
        temperature=TEMP_EXTRACT,
    )
    return result.forms


async def detect_forms(
    llm: LLMClient, tender_pages: list[PageText], evidence: list[EvidenceItem], run_id: str
) -> list[TenderForm]:
    """FINANCIAL forms: all values None. Signature/stamp/date/declaration fields: NEEDS_INPUT."""
    pages = candidate_pages(tender_pages)
    if not pages:
        log.info("form_detection.no_candidates", run_id=run_id)
        return []
    windows = build_windows(pages)
    detected_lists = await gather_limited(
        windows, lambda w: _detect(llm, w, run_id), llm_concurrency()
    )
    detected: list[TenderForm] = []
    seen: set[str] = set()
    for forms in detected_lists:
        for form in forms:
            key = form.form_code.strip().lower()
            if key not in seen:
                seen.add(key)
                detected.append(_blank(form))
    if not detected:
        return []

    codes = {e.evidence_code for e in evidence}
    to_fill = [f for f in detected if f.envelope != "FINANCIAL"]
    filled_by_code: dict[str, TenderForm] = {}
    if to_fill:
        prompt = load_prompt("form_extract")
        task = FILL_TASK.format(
            forms=wrap_data("detected-forms", [f.model_dump(mode="json") for f in to_fill]),
            evidence=wrap_data("evidence-register", [evidence_view(e) for e in evidence]),
        )
        filled = await llm.structured(
            system=prompt.system(),
            user=prompt.user(task=task),
            schema=TenderFormList,
            model_tier="fast",
            run_id=run_id,
            node=NODE,
            prompt_version=f"{prompt.prompt_version}:fill",
            temperature=TEMP_EXTRACT,
        )
        filled_by_code = {f.form_code.strip().lower(): f for f in filled.forms}

    out = [
        enforce_rules(_merge_fill(f, filled_by_code.get(f.form_code.strip().lower())), codes)
        for f in detected
    ]
    log.info(
        "form_detection.done",
        run_id=run_id,
        forms=len(out),
        financial=sum(f.envelope == "FINANCIAL" for f in out),
    )
    return out
