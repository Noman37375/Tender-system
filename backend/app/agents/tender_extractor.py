"""tender_extract map/reduce/override (PRD 7.3, prompts A.1-A.3). OWNER: agents agent.

LLM calls (all node="tender_extract"):
- map: one call per ~12k-token page window, schema TenderRequirements, prompt
  "tender_extract_map@1", fast tier, run concurrently (LLM_CONCURRENCY).
- reduce: one call, schema TenderReduceResult, prompt "tender_extract_reduce@1", strong tier —
  ONLY when there is more than one window (a single window is already consolidated).
  TenderReduceResult's fields are a subset of TenderRequirements' (extra keys are ignored), so
  a TenderRequirements fixture also validates as a reduce answer.
- apply_addendum: one call per addendum, schema AddendumChanges, prompt "addendum_apply@1".
"""

import re
from collections.abc import Iterable

import structlog
from pydantic import BaseModel
from rapidfuzz import fuzz

from app.agents._common import (
    TEMP_EXTRACT,
    build_windows,
    gather_limited,
    llm_concurrency,
    page_lookup,
    requirement_view,
)
from app.llm.adapter import LLMClient
from app.prompts.loader import load_prompt, wrap_data, wrap_pages
from app.rules import quote_verify
from app.schemas.common import Confidence, SourceRef
from app.schemas.pages import PageText
from app.schemas.tender import (
    REQ_CODE_PREFIX,
    AddendumChanges,
    EvaluationCriterion,
    Requirement,
    TenderMetadata,
    TenderRequirements,
)

log = structlog.get_logger(__name__)

NODE = "tender_extract"
DEDUPE_THRESHOLD = 90  # PRD 7.3: rapidfuzz >= 90 within the same category
_CONFIDENCE_RANK = {Confidence.HIGH: 3, Confidence.MEDIUM: 2, Confidence.LOW: 1}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


class TenderReduceResult(BaseModel):
    """Output of tender_extract_reduce.md."""

    merge_groups: list[list[int]] = []  # candidate ids that state the same obligation
    metadata: TenderMetadata | None = None
    prescribed_structure: list[str] = []
    extraction_warnings: list[str] = []


# ------------------------------------------------------------------ deterministic merge
def normalise(text: str) -> str:
    return _NON_ALNUM.sub(" ", text.lower()).strip()


def _same_threshold(a: Requirement, b: Requirement) -> bool:
    if a.criterion is None or b.criterion is None:
        return True
    return a.criterion.model_dump() == b.criterion.model_dump()


def _combine(primary: Requirement, other: Requirement) -> Requirement:
    """Keep the higher-confidence item (ties: the longer description). Mandatory if either is."""
    a, b = primary, other
    if (_CONFIDENCE_RANK[b.confidence], len(b.description)) > (
        _CONFIDENCE_RANK[a.confidence],
        len(a.description),
    ):
        a, b = b, a
    return a.model_copy(
        update={
            "is_mandatory": a.is_mandatory or b.is_mandatory,
            "criterion": a.criterion or b.criterion,
        }
    )


def merge_requirements(groups: Iterable[list[Requirement]]) -> list[Requirement]:
    """Dedupe by fuzzy similarity (token_sort_ratio >= 90 on normalised text) within the same
    category, never merging different thresholds. Output keeps first-appearance order.

    The schema holds one SourceRef per requirement, so the kept item's source is the one
    retained (decision logged in DECISIONS.md)."""
    merged: list[Requirement] = []
    norms: list[str] = []
    for group in groups:
        for req in group:
            norm = normalise(req.description)
            for i, existing in enumerate(merged):
                if (
                    existing.category == req.category
                    and _same_threshold(existing, req)
                    and fuzz.token_sort_ratio(norms[i], norm) >= DEDUPE_THRESHOLD
                ):
                    merged[i] = _combine(existing, req)
                    norms[i] = normalise(merged[i].description)
                    break
            else:
                merged.append(req)
                norms.append(norm)
    return merged


def apply_merge_groups(
    reqs: list[Requirement], groups: list[list[int]]
) -> tuple[list[Requirement], list[str]]:
    """Apply the reduce call's merge groups (indices into reqs). Groups that mix categories or
    thresholds are refused with a warning (prompt A.2 rule 2 enforced in code)."""
    warnings: list[str] = []
    drop: set[int] = set()
    result = list(reqs)
    for group in groups:
        ids = sorted({i for i in group if 0 <= i < len(reqs) and i not in drop})
        if len(ids) < 2:
            continue
        items = [reqs[i] for i in ids]
        if len({r.category for r in items}) > 1 or not all(
            _same_threshold(items[0], r) for r in items[1:]
        ):
            warnings.append(f"Reduce step proposed merging incompatible requirements {ids}; kept.")
            continue
        kept = items[0]
        for other in items[1:]:
            kept = _combine(kept, other)
        result[ids[0]] = kept
        drop.update(ids[1:])
    return [r for i, r in enumerate(result) if i not in drop], warnings


def merge_metadata(parts: list[TenderMetadata]) -> TenderMetadata:
    """First non-null value per field in window order; sources are unioned."""
    out = TenderMetadata()
    sources: list[SourceRef] = []
    seen: set[tuple[str, int, str]] = set()
    for part in parts:
        for field in (
            "title",
            "reference_no",
            "procuring_entity",
            "submission_deadline",
            "bid_validity_days",
            "bid_security",
            "submission_method",
        ):
            if getattr(out, field) is None and getattr(part, field) is not None:
                setattr(out, field, getattr(part, field))
        if not out.scope_summary and part.scope_summary:
            out.scope_summary = part.scope_summary
        for src in part.sources:
            key = (src.document_id, src.page, src.quote)
            if key not in seen:
                seen.add(key)
                sources.append(src)
    out.sources = sources
    return out


def _overlay_metadata(base: TenderMetadata, override: TenderMetadata | None) -> TenderMetadata:
    if override is None:
        return base
    update = {
        k: v
        for k, v in override.model_dump().items()
        if k not in ("sources", "scope_summary") and v is not None
    }
    if override.scope_summary:
        update["scope_summary"] = override.scope_summary
    merged = base.model_copy(update=update)
    if override.sources:
        merged.sources = merge_metadata([base, override]).sources
    return merged


def merge_evaluation_criteria(
    groups: Iterable[list[EvaluationCriterion]],
) -> list[EvaluationCriterion]:
    out: list[EvaluationCriterion] = []
    seen: set[str] = set()
    for group in groups:
        for crit in group:
            key = normalise(crit.name)
            if key not in seen:
                seen.add(key)
                out.append(crit)
    return out


def _code_number(code: str, prefix: str) -> int | None:
    match = re.fullmatch(rf"{prefix}-(\d+)", code)
    return int(match.group(1)) if match else None


def assign_codes(reqs: list[Requirement], existing_codes: Iterable[str] = ()) -> list[Requirement]:
    """ELG-001, FIN-001 ... per category in list order, continuing after any existing codes."""
    next_no: dict[str, int] = {}
    for prefix in REQ_CODE_PREFIX.values():
        numbers = [n for c in existing_codes if (n := _code_number(c, prefix)) is not None]
        next_no[prefix] = max(numbers, default=0) + 1
    out: list[Requirement] = []
    for req in reqs:
        prefix = REQ_CODE_PREFIX[req.category]
        out.append(req.model_copy(update={"req_code": f"{prefix}-{next_no[prefix]:03d}"}))
        next_no[prefix] += 1
    return out


def verify_sources(
    reqs: list[Requirement], pages: dict[tuple[str, int], str], label: str = "Requirement"
) -> tuple[list[Requirement], list[str]]:
    """Quote verification (PRD 7.3 step 5): failures -> confidence LOW + warning; never drop."""
    out: list[Requirement] = []
    warnings: list[str] = []
    for req in reqs:
        page_text = pages.get((req.source.document_id, req.source.page))
        ok = page_text is not None and quote_verify.verify_quote(req.source.quote, page_text)
        if ok:
            out.append(req)
            continue
        out.append(req.model_copy(update={"confidence": Confidence.LOW}))
        where = f"document {req.source.document_id} page {req.source.page}"
        reason = "cited page not provided" if page_text is None else "quote not found on page"
        warnings.append(
            f"{label} {req.req_code}: source quote could not be verified ({reason}, {where}); "
            "confidence set to LOW."
        )
    return out, warnings


# ------------------------------------------------------------------ map / reduce
async def _map_window(llm: LLMClient, window: list[PageText], run_id: str) -> TenderRequirements:
    prompt = load_prompt("tender_extract_map")
    user = prompt.user(
        page_start=window[0].page_no,
        page_end=window[-1].page_no,
        document_id=window[0].document_id,
        pages=wrap_pages(window),
    )
    return await llm.structured(
        system=prompt.system(),
        user=user,
        schema=TenderRequirements,
        model_tier="fast",
        run_id=run_id,
        node=NODE,
        prompt_version=prompt.prompt_version,
        temperature=TEMP_EXTRACT,
    )


async def _reduce(
    llm: LLMClient, reqs: list[Requirement], partials: list[TenderRequirements], run_id: str
) -> TenderReduceResult:
    prompt = load_prompt("tender_extract_reduce")
    candidates = [{"id": i, **requirement_view(r, with_source=True)} for i, r in enumerate(reqs)]
    metadata = [p.metadata.model_dump(mode="json") for p in partials]
    structures = [p.prescribed_structure for p in partials if p.prescribed_structure]
    user = prompt.user(
        requirements_json=wrap_data("candidate-requirements", candidates),
        metadata_json=wrap_data("candidate-metadata", metadata),
        structure_json=wrap_data("candidate-structures", structures),
    )
    return await llm.structured(
        system=prompt.system(),
        user=user,
        schema=TenderReduceResult,
        model_tier="strong",
        run_id=run_id,
        node=NODE,
        prompt_version=prompt.prompt_version,
        temperature=TEMP_EXTRACT,
    )


async def extract_tender(llm: LLMClient, pages: list[PageText], run_id: str) -> TenderRequirements:
    """Map windows (~12k tokens) concurrently -> deterministic merge (rapidfuzz >= 90) -> reduce
    call -> assign req codes -> quote verification (LOW confidence + warning, never drop)."""
    if not pages:
        return TenderRequirements(
            metadata=TenderMetadata(),
            requirements=[],
            extraction_warnings=["No tender pages were provided for extraction."],
        )
    windows = build_windows(pages)
    partials = await gather_limited(
        windows, lambda w: _map_window(llm, w, run_id), llm_concurrency()
    )
    warnings: list[str] = [w for p in partials for w in p.extraction_warnings]
    reqs = merge_requirements(p.requirements for p in partials)
    metadata = merge_metadata([p.metadata for p in partials])
    structure = next((p.prescribed_structure for p in partials if p.prescribed_structure), [])

    if len(partials) > 1:
        reduced = await _reduce(llm, reqs, partials, run_id)
        reqs, merge_warnings = apply_merge_groups(reqs, reduced.merge_groups)
        warnings += merge_warnings + reduced.extraction_warnings
        metadata = _overlay_metadata(metadata, reduced.metadata)
        structure = reduced.prescribed_structure or structure

    reqs = assign_codes(reqs)
    reqs, quote_warnings = verify_sources(reqs, page_lookup(pages))
    warnings += quote_warnings
    log.info(
        "tender_extract.done",
        run_id=run_id,
        windows=len(windows),
        requirements=len(reqs),
        low_confidence=sum(r.confidence == Confidence.LOW for r in reqs),
    )
    return TenderRequirements(
        metadata=metadata,
        requirements=reqs,
        evaluation_criteria=merge_evaluation_criteria(p.evaluation_criteria for p in partials),
        prescribed_structure=structure,
        extraction_warnings=list(dict.fromkeys(warnings)),
    )


# ------------------------------------------------------------------ addenda
_METADATA_FIELDS = set(TenderMetadata.model_fields) - {"sources"}


async def apply_addendum(
    llm: LLMClient, current: TenderRequirements, addendum_pages: list[PageText], run_id: str
) -> AddendumChanges:
    """One LLM call per addendum. Post-processing in code:
    - modified with an unknown req_code -> treated as added (never silently dropped);
    - added get fresh codes continuing each category's numbering;
    - deleted codes that do not exist are ignored;
    - metadata_changes limited to TenderMetadata fields;
    - quotes verified against the addendum pages (LOW confidence on failure).
    """
    if not addendum_pages:
        return AddendumChanges()
    prompt = load_prompt("addendum_apply")
    user = prompt.user(
        requirements_json=wrap_data(
            "current-requirements", [requirement_view(r) for r in current.requirements]
        ),
        document_id=addendum_pages[0].document_id,
        pages=wrap_pages(addendum_pages),
    )
    changes = await llm.structured(
        system=prompt.system(),
        user=user,
        schema=AddendumChanges,
        model_tier="strong",
        run_id=run_id,
        node=NODE,
        prompt_version=prompt.prompt_version,
        temperature=TEMP_EXTRACT,
    )
    known = {r.req_code for r in current.requirements}
    modified = [m for m in changes.modified if m.req_code in known]
    unknown_modified = [m for m in changes.modified if m.req_code not in known]
    added = assign_codes([*unknown_modified, *changes.added], existing_codes=known)
    lookup = page_lookup(addendum_pages)
    modified, _ = verify_sources(modified, lookup, label="Addendum change to")
    added, _ = verify_sources(added, lookup, label="Addendum addition")
    deleted = [c for c in dict.fromkeys(changes.deleted_req_codes) if c in known]
    if unknown_modified:
        log.warning("addendum.unknown_modified_codes", run_id=run_id, count=len(unknown_modified))
    return AddendumChanges(
        modified=modified,
        added=added,
        deleted_req_codes=deleted,
        deletion_sources=changes.deletion_sources,
        metadata_changes={
            k: v for k, v in changes.metadata_changes.items() if k in _METADATA_FIELDS
        },
    )


def apply_changes(current: TenderRequirements, changes: AddendumChanges) -> TenderRequirements:
    """Pure helper: the active requirement list after an addendum (modified replace by code,
    added appended, deleted removed, metadata updated). Persistence (superseded_by) is the
    graph's job; this gives it and the tests the resulting view."""
    by_code = {m.req_code: m for m in changes.modified}
    deleted = set(changes.deleted_req_codes)
    reqs = [by_code.get(r.req_code, r) for r in current.requirements if r.req_code not in deleted]
    reqs += changes.added
    meta_update: dict[str, object] = {}
    for key, value in changes.metadata_changes.items():
        if key == "bid_validity_days" and value is not None:
            digits = re.search(r"\d+", value)
            meta_update[key] = int(digits.group()) if digits else None
        elif key == "scope_summary":
            meta_update[key] = value or current.metadata.scope_summary
        else:
            meta_update[key] = value
    return current.model_copy(
        update={
            "requirements": reqs,
            "metadata": current.metadata.model_copy(update=meta_update),
        }
    )
