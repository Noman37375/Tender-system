"""Helpers shared by the LLM agents: windows, concurrency, temperatures, JSON views."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from app.llm.client import estimate_tokens
from app.prompts.loader import page_text_with_tables
from app.schemas.evidence import EvidenceItem
from app.schemas.pages import PageText
from app.schemas.tender import Requirement

WINDOW_TOKENS = 12_000  # PRD 7.3 tender_extract map windows

# PRD 9: <= 0.2 for extraction/compliance/audit, <= 0.4 for writing.
TEMP_EXTRACT = 0.1
TEMP_DESIGN = 0.3
TEMP_WRITE = 0.3

DEFAULT_CONCURRENCY = 4


def llm_concurrency() -> int:
    """settings.LLM_CONCURRENCY, or the default when settings cannot be loaded."""
    try:
        from app.config import get_settings

        return max(1, get_settings().LLM_CONCURRENCY)
    except Exception:  # settings need DATABASE_URL etc.; agents must not depend on them
        return DEFAULT_CONCURRENCY


async def gather_limited[A, R](
    items: Iterable[A], fn: Callable[[A], Awaitable[R]], concurrency: int
) -> list[R]:
    """Run fn over items with at most `concurrency` in flight; results keep input order."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def run(item: A) -> R:
        async with semaphore:
            return await fn(item)

    return list(await asyncio.gather(*(run(i) for i in items)))


def page_tokens(page: PageText) -> int:
    return estimate_tokens(page_text_with_tables(page))


def build_windows(pages: list[PageText], max_tokens: int = WINDOW_TOKENS) -> list[list[PageText]]:
    """Page-aligned windows of ~max_tokens. Never splits a page, never crosses a document
    boundary; pages keep their input order (callers pass documents in reading order)."""
    windows: list[list[PageText]] = []
    current: list[PageText] = []
    used = 0
    for page in pages:
        tokens = page_tokens(page)
        crosses_doc = bool(current) and current[-1].document_id != page.document_id
        if current and (crosses_doc or used + tokens > max_tokens):
            windows.append(current)
            current, used = [], 0
        current.append(page)
        used += tokens
    if current:
        windows.append(current)
    return windows


def page_lookup(pages: Iterable[PageText]) -> dict[tuple[str, int], str]:
    return {(p.document_id, p.page_no): page_text_with_tables(p) for p in pages}


def requirement_view(req: Requirement, *, with_source: bool = False) -> dict[str, Any]:
    view: dict[str, Any] = {
        "req_code": req.req_code,
        "category": req.category.value,
        "description": req.description,
        "is_mandatory": req.is_mandatory,
        "criterion": req.criterion.model_dump(mode="json") if req.criterion else None,
    }
    if with_source:
        view["source"] = req.source.model_dump(mode="json")
    return view


def evidence_view(item: EvidenceItem) -> dict[str, Any]:
    return {
        "evidence_code": item.evidence_code,
        "category": item.category.value,
        "description": item.description,
        "attributes": item.attributes,
        "verification_status": item.verification_status.value,
    }
