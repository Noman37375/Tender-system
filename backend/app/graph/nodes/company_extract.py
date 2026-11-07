"""company_extract node (PRD 7.3 company_extract).

- Documents with `evidence_extracted_at` set are skipped; their stored evidence is reused (step 6).
- New items get `EV-<prefix>-NNN` codes, NNN = organisation max + 1, assigned inside the persist
  transaction under a per-organisation advisory lock; codes are never reused.
- EXPIRED is never stored (step 3); the run-scoped `company_evidence` applies
  `app.rules.evidence_status.effective_status` against today and the tender deadline.
"""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import company_extractor
from app.db.models import EvidenceItem as EvidenceRow
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.repositories.results import ResultsRepository, evidence_to_schema
from app.repositories.runs import now
from app.rules.evidence_status import effective_status
from app.schemas.evidence import (
    EVIDENCE_CODE_PREFIX,
    CompanyEvidence,
    EvidenceItem,
    VerificationStatus,
)

NAME = "company_extract"


def stored_status(item: EvidenceItem) -> str:
    """Status safe to store: EXPIRED is run-scoped, so it is never written to the DB.

    An item the extractor already marked EXPIRED is stored as DOCUMENTED only when it carries an
    expiry date (so each run recomputes EXPIRED from that date); otherwise UNVERIFIED.
    """
    if item.verification_status is VerificationStatus.EXPIRED:
        return "DOCUMENTED" if item.attributes.get("expiry_date") else "UNVERIFIED"
    return item.verification_status.value


def run_scoped(items: list[EvidenceItem], deadline: date | None, today: date) -> list[EvidenceItem]:
    return [
        item.model_copy(update={"verification_status": effective_status(item, deadline, today)})
        for item in items
    ]


async def assign_and_store(
    session: AsyncSession,
    organisation_id: uuid.UUID,
    new_items: list[tuple[uuid.UUID, EvidenceItem]],
    extracted_document_ids: list[uuid.UUID],
) -> list[EvidenceItem]:
    """Persist newly extracted evidence with fresh codes; returns the items with their codes."""
    repo = ResultsRepository(session)
    await repo.lock_evidence_codes(organisation_id)
    # idempotent retry: drop rows of documents this node is (re)extracting
    for row in await repo.evidence_for_documents(organisation_id, extracted_document_ids):
        await session.delete(row)
    await session.flush()
    next_number: dict[str, int] = {}
    stored: list[EvidenceItem] = []
    for document_id, item in new_items:
        prefix = EVIDENCE_CODE_PREFIX[item.category]
        if prefix not in next_number:
            next_number[prefix] = await repo.max_evidence_number(organisation_id, prefix) + 1
        code = f"EV-{prefix}-{next_number[prefix]:03d}"
        next_number[prefix] += 1
        status = stored_status(item)
        session.add(
            EvidenceRow(
                organisation_id=organisation_id,
                evidence_code=code,
                category=item.category.value,
                description=item.description,
                attributes=item.attributes,
                source_document_id=document_id,
                source_page=item.source.page,
                source_quote=item.source.quote,
                verification_status=status,
            )
        )
        stored.append(
            item.model_copy(
                update={
                    "evidence_code": code,
                    "verification_status": VerificationStatus(status),
                    "source": item.source.model_copy(update={"document_id": str(document_id)}),
                }
            )
        )
    for doc in await repo.documents(organisation_id, extracted_document_ids):
        doc.evidence_extracted_at = now()
    await session.flush()
    return stored


async def work(call: NodeCall) -> NodeOutput:
    ids = [uuid.UUID(d) for d in call.state.get("company_document_ids", [])]
    async with call.session() as session:
        repo = ResultsRepository(session)
        docs = await repo.documents(call.organisation_id, ids)
        done_docs = [d for d in docs if d.evidence_extracted_at is not None]
        todo_docs = [d for d in docs if d.evidence_extracted_at is None]
        reused = [
            evidence_to_schema(r)
            for r in await repo.evidence_for_documents(
                call.organisation_id, [d.id for d in done_docs]
            )
        ]
        tender = await repo.get_tender(call.organisation_id, call.tender_id)
        deadline = (
            tender.submission_deadline.date() if tender and tender.submission_deadline else None
        )
        pages_by_doc = {d.id: await repo.pages(call.organisation_id, d.id) for d in todo_docs}
        kinds = {d.id: d.kind for d in todo_docs}

    company_name: str | None = None
    warnings: list[str] = []
    new_items: list[tuple[uuid.UUID, EvidenceItem]] = []
    for done, (document_id, pages) in enumerate(pages_by_doc.items(), start=1):
        extracted = await company_extractor.extract_company_document(
            call.llm, kinds[document_id], pages, str(call.run_id)
        )
        part = CompanyEvidence.model_validate(extracted.model_dump())
        company_name = company_name or part.company_name
        warnings.extend(part.extraction_warnings)
        new_items.extend((document_id, item) for item in part.items)
        await call.progress("company documents extracted", done, len(pages_by_doc))

    # codes exist only after the persist transaction assigns them, so the state is filled there
    output = NodeOutput(state={})

    async def persist(session: AsyncSession) -> None:
        stored = await assign_and_store(
            session, call.organisation_id, new_items, list(pages_by_doc)
        )
        evidence = CompanyEvidence(
            company_name=company_name,
            items=run_scoped(reused + stored, deadline, call.ctx.today()),
            extraction_warnings=warnings,
        )
        dumped = evidence.model_dump(mode="json")
        output.state.update({"company_evidence": dumped, "warnings": warnings})
        output.output = dumped
        output.summary = f"{len(evidence.items)} evidence items ({len(stored)} new)"

    output.persist = persist
    return output


company_extract = graph_node(NAME)(work)
