"""tender_extract node (PRD 7.3): map/reduce extraction + addendum override.

The extraction itself (windows, merge, codes, quote verification) is app.agents.tender_extractor.
This node loads pages, applies addenda in `addendum_seq` order, and persists `requirements`
(with `superseded_by` for overridden or deleted rows) and the tender metadata.
"""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import tender_extractor
from app.db.models import Document
from app.db.models import Requirement as RequirementRow
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.repositories.results import ResultsRepository
from app.schemas.pages import PageText
from app.schemas.tender import (
    REQ_CODE_PREFIX,
    AddendumChanges,
    Requirement,
    TenderMetadata,
    TenderRequirements,
)

NAME = "tender_extract"
DELETED = "__deleted__"


class NoTenderDocumentError(RuntimeError):
    pass


def _base_code(code: str) -> str:
    return re.sub(r"-A\d+$", "", code)


def _next_code(req: Requirement, used: set[str]) -> str:
    prefix = REQ_CODE_PREFIX[req.category]
    numbers = [
        int(m.group(1)) for c in used if (m := re.fullmatch(rf"{prefix}-(\d+)", c)) is not None
    ]
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


def apply_changes(
    current: TenderRequirements,
    all_reqs: dict[str, Requirement],
    superseded: dict[str, str],
    changes: AddendumChanges,
    seq: int,
    warnings: list[str],
) -> TenderRequirements:
    """Apply one addendum (PRD tender_extract step 4).

    `all_reqs` keeps every requirement ever produced (all are persisted) and `superseded` maps
    old req_code -> replacing req_code, or DELETED. A modified requirement gets a new code
    `<base>-A<seq>` because (tender_id, req_code) is unique and the old row is kept.
    """
    active = {r.req_code: r for r in current.requirements}
    for mod in changes.modified:
        if mod.req_code not in active:
            warnings.append(f"Addendum {seq} modifies unknown requirement {mod.req_code}")
            continue
        new_code = f"{_base_code(mod.req_code)}-A{seq}"
        new_req = mod.model_copy(update={"req_code": new_code})
        superseded[mod.req_code] = new_code
        del active[mod.req_code]
        active[new_code] = new_req
        all_reqs[new_code] = new_req
    for code in changes.deleted_req_codes:
        if code not in active:
            warnings.append(f"Addendum {seq} deletes unknown requirement {code}")
            continue
        superseded[code] = DELETED
        del active[code]
    for added in changes.added:
        code = added.req_code
        if not code or code == "TBD" or code in all_reqs:
            code = _next_code(added, set(all_reqs))
        new_req = added.model_copy(update={"req_code": code})
        active[code] = new_req
        all_reqs[code] = new_req
    metadata = current.metadata.model_copy(
        update={
            k: v for k, v in changes.metadata_changes.items() if k in TenderMetadata.model_fields
        }
    )
    return current.model_copy(
        update={
            "metadata": metadata,
            "requirements": sorted(active.values(), key=lambda r: r.req_code),
        }
    )


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def _persist_requirements(
    session: AsyncSession,
    call: NodeCall,
    all_reqs: dict[str, Requirement],
    superseded: dict[str, str],
    result: TenderRequirements,
) -> None:
    repo = ResultsRepository(session)
    known_docs = {uuid.UUID(d) for d in call.state.get("tender_document_ids", [])}
    existing = {
        r.req_code: r
        for r in await repo.requirements(call.organisation_id, call.tender_id, active_only=False)
    }
    for old_row in existing.values():  # clear old links so rows can be re-pointed or deleted
        old_row.superseded_by = None
    await session.flush()
    rows: dict[str, RequirementRow] = {}
    for code, req in all_reqs.items():
        row = existing.get(code)
        if row is None:
            row = RequirementRow(organisation_id=call.organisation_id, tender_id=call.tender_id)
            session.add(row)
        row.req_code = code
        row.category = req.category.value
        row.description = req.description
        row.is_mandatory = req.is_mandatory
        row.criterion = req.criterion.model_dump(mode="json") if req.criterion else None
        source_doc = _uuid_or_none(req.source.document_id)
        row.source_document_id = source_doc if source_doc in known_docs else None
        row.source_page = req.source.page
        row.source_quote = req.source.quote
        row.extraction_confidence = req.confidence.value
        rows[code] = row
    await session.flush()
    for old, new in superseded.items():
        rows[old].superseded_by = rows[old].id if new == DELETED else rows[new].id
    for code, stale in existing.items():
        if code in rows:
            continue
        if await repo.requirement_is_referenced(call.organisation_id, stale.id):
            stale.superseded_by = stale.id  # withdrawn; earlier runs' records still point here
        else:
            await session.delete(stale)
    tender = await repo.get_tender(call.organisation_id, call.tender_id)
    if tender is not None:
        meta = result.metadata
        if meta.title and not tender.title:
            tender.title = meta.title
        if meta.reference_no:
            tender.reference_no = meta.reference_no
        if meta.procuring_entity:
            tender.procuring_entity = meta.procuring_entity
        deadline = _parse_datetime(meta.submission_deadline)
        if deadline is not None:
            tender.submission_deadline = deadline


async def _load(call: NodeCall) -> tuple[list[PageText], list[tuple[int, list[PageText]]]]:
    ids = [uuid.UUID(d) for d in call.state.get("tender_document_ids", [])]
    async with call.session() as session:
        repo = ResultsRepository(session)
        docs: list[Document] = await repo.documents(call.organisation_id, ids)
        tender_docs = sorted((d for d in docs if d.kind == "TENDER"), key=lambda d: d.created_at)
        addenda = sorted(
            (d for d in docs if d.kind == "ADDENDUM"),
            key=lambda d: (d.addendum_seq or 0, d.created_at),
        )
        if not tender_docs:
            raise NoTenderDocumentError("run has no TENDER document")
        pages: list[PageText] = []
        for doc in tender_docs:
            pages.extend(await repo.pages(call.organisation_id, doc.id))
        addendum_pages = [
            (doc.addendum_seq or i, await repo.pages(call.organisation_id, doc.id))
            for i, doc in enumerate(addenda, start=1)
        ]
    return pages, addendum_pages


async def work(call: NodeCall) -> NodeOutput:
    pages, addenda = await _load(call)
    extracted = await tender_extractor.extract_tender(call.llm, pages, str(call.run_id))
    result = TenderRequirements.model_validate(extracted.model_dump())
    all_reqs: dict[str, Requirement] = {r.req_code: r for r in result.requirements}
    if len(all_reqs) != len(result.requirements):
        raise ValueError("tender extraction returned duplicate req_codes")
    superseded: dict[str, str] = {}
    warnings = list(result.extraction_warnings)
    for done, (seq, addendum_pages) in enumerate(addenda, start=1):
        changes = await tender_extractor.apply_addendum(
            call.llm, result, addendum_pages, str(call.run_id)
        )
        result = apply_changes(result, all_reqs, superseded, changes, seq, warnings)
        await call.progress("addenda applied", done, len(addenda))
    result = result.model_copy(update={"extraction_warnings": warnings})

    async def persist(session: AsyncSession) -> None:
        await _persist_requirements(session, call, all_reqs, superseded, result)

    dumped = result.model_dump(mode="json")
    return NodeOutput(
        state={"tender_requirements": dumped, "warnings": warnings},
        persist=persist,
        output={**dumped, "superseded": superseded},
        summary=f"{len(result.requirements)} active requirements",
    )


tender_extract = graph_node(NAME)(work)
