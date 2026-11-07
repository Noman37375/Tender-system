"""form_detection node (PRD 7.3): prescribed forms, persisted to tender_forms.

Defensive rules in code (the agent applies them too): FINANCIAL forms are never filled
(SKIPPED_FINANCIAL, all values cleared). Fields still needing input become missing-information
items in state; they are not written to missing_items (that table is owned by compliance).
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import form_detector
from app.db.models import TenderForm as TenderFormRow
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.repositories.results import ResultsRepository
from app.schemas.compliance import MissingInfo
from app.schemas.evidence import CompanyEvidence
from app.schemas.forms import FormField, TenderForm
from app.schemas.pages import PageText

NAME = "form_detection"


def enforce_rules(form: TenderForm) -> tuple[TenderForm, str]:
    """Return the form with financial values cleared, and its fill_status."""
    if form.envelope == "FINANCIAL":
        cleared = [
            f.model_copy(update={"value": None, "evidence_codes": [], "status": "NEEDS_INPUT"})
            for f in form.fields
        ]
        return form.model_copy(update={"fields": cleared}), "SKIPPED_FINANCIAL"
    applicable = [f for f in form.fields if f.status != "NOT_APPLICABLE"]
    filled = [f for f in applicable if f.status == "FILLED"]
    if not applicable or len(filled) == len(applicable):
        status = "FILLED" if applicable else "EMPTY"
    elif not filled:
        status = "EMPTY"
    else:
        status = "PARTIAL"
    return form, status


def _missing(form: TenderForm, field: FormField) -> MissingInfo:
    return MissingInfo(
        item=f"{form.form_code}: {field.label}",
        reason=f"Prescribed form '{form.title}' field needs client input",
        severity="MEDIUM",
    )


async def work(call: NodeCall) -> NodeOutput:
    ids = [uuid.UUID(d) for d in call.state.get("tender_document_ids", [])]
    async with call.session() as session:
        repo = ResultsRepository(session)
        docs = sorted(
            await repo.documents(call.organisation_id, ids),
            key=lambda d: (d.kind != "TENDER", d.addendum_seq or 0, d.created_at),
        )
        pages: list[PageText] = []
        for doc in docs:
            pages.extend(await repo.pages(call.organisation_id, doc.id))
    evidence = CompanyEvidence.model_validate(call.state["company_evidence"]).items
    detected = await form_detector.detect_forms(call.llm, pages, evidence, str(call.run_id))
    forms: list[tuple[TenderForm, str]] = [
        enforce_rules(TenderForm.model_validate(f.model_dump())) for f in detected
    ]
    missing = [
        _missing(form, field)
        for form, status in forms
        if status != "SKIPPED_FINANCIAL"
        for field in form.fields
        if field.status == "NEEDS_INPUT"
    ]

    async def persist(session: AsyncSession) -> None:
        await ResultsRepository(session).delete_run_rows(
            TenderFormRow, call.organisation_id, call.run_id
        )
        for form, status in forms:
            session.add(
                TenderFormRow(
                    organisation_id=call.organisation_id,
                    run_id=call.run_id,
                    form_code=form.form_code,
                    title=form.title,
                    source_page=form.source_page,
                    envelope=form.envelope,
                    fields=[f.model_dump(mode="json") for f in form.fields],
                    fill_status=status,
                )
            )

    dumped = [form.model_dump(mode="json") for form, _ in forms]
    return NodeOutput(
        state={
            "tender_forms": dumped,
            "missing_information": [m.model_dump(mode="json") for m in missing],
        },
        persist=persist,
        output={"forms": dumped},
        summary=f"{len(forms)} forms",
    )


form_detection = graph_node(NAME)(work)
