"""compliance node (PRD 7.3 compliance): LLM matching + rules engine + missing items.

Also refreshes the run-scoped evidence statuses: company_extract runs in parallel with
tender_extract and may not have known the tender deadline yet. EXPIRED only ever gets added by a
later deadline, so recomputing here is idempotent. The refreshed `company_evidence` is returned
so later nodes (writer, audit) see the same statuses the rules engine used.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import compliance_matcher
from app.db.models import ComplianceRecord as ComplianceRow
from app.db.models import MissingItem as MissingRow
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node, parse_deadline
from app.graph.nodes.company_extract import run_scoped
from app.repositories.results import ResultsRepository
from app.rules import bid_decision as bid_rules
from app.rules.compliance_rules import apply_rules
from app.schemas.compliance import ComplianceRecord, MissingInfo
from app.schemas.evidence import CompanyEvidence
from app.schemas.tender import TenderRequirements

NAME = "compliance"


class ComplianceInvariantError(RuntimeError):
    """len(compliance_matrix) != len(active requirements) (PRD compliance step 5)."""


async def work(call: NodeCall) -> NodeOutput:
    tender_reqs = TenderRequirements.model_validate(call.state["tender_requirements"])
    company = CompanyEvidence.model_validate(call.state["company_evidence"])
    async with call.session() as session:
        repo = ResultsRepository(session)
        active_rows = await repo.requirements(call.organisation_id, call.tender_id)
        tender = await repo.get_tender(call.organisation_id, call.tender_id)
    deadline = parse_deadline(tender_reqs.metadata.submission_deadline) or (
        tender.submission_deadline.date() if tender and tender.submission_deadline else None
    )
    items = run_scoped(company.items, deadline, call.ctx.today())
    company = company.model_copy(update={"items": items})
    requirements = tender_reqs.requirements

    candidates = await compliance_matcher.select_candidates(call.llm, requirements, items)
    matches = await compliance_matcher.match_requirements(
        call.llm, candidates, requirements, str(call.run_id)
    )
    match_by_code = {m.req_code: m for m in matches}
    evidence_by_code = {i.evidence_code: i for i in items}
    records: list[ComplianceRecord] = []
    warnings: list[str] = []
    for req in requirements:
        match = match_by_code.get(req.req_code)
        if match is None:
            continue  # caught by the invariant below
        record, rule_warnings = apply_rules(match, req, evidence_by_code, deadline)
        records.append(ComplianceRecord.model_validate(record.model_dump()))
        warnings.extend(rule_warnings)

    active_codes = {r.req_code for r in active_rows}
    record_codes = [r.req_code for r in records]
    if len(records) != len(active_rows) or set(record_codes) != active_codes:
        raise ComplianceInvariantError(
            f"{len(records)} compliance records for {len(active_rows)} active requirements"
        )
    missing = [
        MissingInfo.model_validate(m.model_dump())
        for m in bid_rules.missing_items(requirements, records)
    ]
    req_ids = {r.req_code: r.id for r in active_rows}

    async def persist(session: AsyncSession) -> None:
        repo = ResultsRepository(session)
        await repo.delete_run_rows(ComplianceRow, call.organisation_id, call.run_id)
        await repo.delete_run_rows(MissingRow, call.organisation_id, call.run_id)
        evidence_ids = await repo.evidence_ids_by_code(
            call.organisation_id, [c for r in records for c in r.evidence_codes]
        )
        for rec in records:
            session.add(
                ComplianceRow(
                    organisation_id=call.organisation_id,
                    run_id=call.run_id,
                    requirement_id=req_ids[rec.req_code],
                    status=rec.status.value,
                    evidence_ids=[evidence_ids[c] for c in rec.evidence_codes if c in evidence_ids],
                    llm_proposed_status=rec.llm_proposed_status.value,
                    rule_applied=rec.rule_applied,
                    rationale=rec.rationale,
                    gap_description=rec.gap_description,
                    action_required=rec.action_required,
                )
            )
        for item in missing:
            session.add(
                MissingRow(
                    organisation_id=call.organisation_id,
                    run_id=call.run_id,
                    item=item.item,
                    reason=item.reason,
                    related_requirement_id=req_ids.get(item.req_code or ""),
                    severity=item.severity,
                )
            )

    matrix = [r.model_dump(mode="json") for r in records]
    counts = {s: sum(1 for r in records if r.status.value == s) for s in ("COMPLIANT", "PARTIAL")}
    return NodeOutput(
        state={
            "compliance_matrix": matrix,
            "missing_information": [m.model_dump(mode="json") for m in missing],
            "company_evidence": company.model_dump(mode="json"),
            "warnings": warnings,
        },
        persist=persist,
        output={"records": matrix, "company_evidence": company.model_dump(mode="json")},
        summary=(
            f"{len(records)} requirements: {counts['COMPLIANT']} compliant, "
            f"{counts['PARTIAL']} partial"
        ),
    )


compliance = graph_node(NAME)(work)
