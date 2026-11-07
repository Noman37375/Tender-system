"""Run lifecycle, results, review, section editing and exports (PRD 10.3, 10.4, 11.2, 12).

Routers call this service; it uses repositories for all DB access and the executor for graph
work. Every lookup is scoped to the caller's organisation (S-01): a run of another organisation
is reported as not found.
"""

import uuid
from collections import Counter
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import section_writer
from app.db.models import AgentStep, MissingItem, ProposalSection, Run, User
from app.errors import ApiError
from app.export.docx_builder import build_proposal_docx
from app.export.xlsx_builder import build_compliance_xlsx
from app.graph.executor import RunBusyError, RunExecutor, budget_from_settings
from app.graph.nodes.write_sections import build_write_context
from app.graph.state import TenderState
from app.llm.adapter import BudgetExceededError, CallUsage
from app.repositories.results import (
    TENDER_KINDS,
    ResultsRepository,
    form_to_schema,
    jsonable,
    missing_to_schema,
    records_to_schema,
    requirement_to_schema,
    section_to_schema,
)
from app.repositories.runs import ACTIVE_RUN_STATUSES, RunRepository
from app.rules.citation_checker import extract_placeholders
from app.schemas import runs_api as api
from app.schemas.audit import AuditReport
from app.schemas.compliance import BidDecision, ComplianceRecord
from app.schemas.evidence import CompanyEvidence, EvidenceItem
from app.schemas.solution import SolutionDesign
from app.schemas.tender import TenderRequirements

log = structlog.get_logger(__name__)

MAX_EXECUTING_RUNS_PER_ORG = 5  # S-08
READ_ONLY_ROLES = {"viewer"}
REGENERATE_NODE = "regenerate_section"


def _not_found(what: str = "Run") -> ApiError:
    return ApiError(404, f"{what.upper().replace(' ', '_')}_NOT_FOUND", f"{what} not found")


def _not_available(what: str) -> ApiError:
    return ApiError(404, "NOT_AVAILABLE", f"{what} is not available for this run yet")


def require_writer(user: User) -> None:
    if user.role in READ_ONLY_ROLES:
        raise ApiError(403, "FORBIDDEN", "Your role cannot change runs")


def section_out(row: ProposalSection) -> api.ProposalSectionOut:
    return api.ProposalSectionOut(
        section_key=row.section_key,
        title=row.title,
        order_index=row.order_index,
        content_md=row.content_md,
        citations=list(row.citations or []),
        placeholders=[str(p) for p in row.placeholders or []],
        edited_by_user=row.edited_by_user,
    )


def missing_out(item: MissingItem, req_code: str | None) -> api.MissingItemOut:
    return api.MissingItemOut(
        id=item.id,
        item=item.item,
        reason=item.reason,
        req_code=req_code,
        severity=item.severity,
        resolved=item.resolved,
    )


def _audit_report(passed: bool, findings: list[Any]) -> AuditReport:
    blocking = {
        f["section_key"]
        for f in findings
        if f.get("section_key") and f.get("severity") in ("BLOCKER", "MAJOR")
    }
    return AuditReport.model_validate(
        {"passed": passed, "findings": findings, "sections_to_revise": sorted(blocking)}
    )


class RunService:
    def __init__(self, session: AsyncSession, executor: RunExecutor) -> None:
        self.session = session
        self.executor = executor
        self.runs = RunRepository(session)
        self.results = ResultsRepository(session)

    # ---- lifecycle (PRD 10.3) -----------------------------------------------------------------
    async def start_run(self, user: User, tender_id: uuid.UUID, body: api.StartRunRequest) -> Run:
        require_writer(user)
        org = user.organisation_id
        tender = await self.results.get_tender(org, tender_id)
        if tender is None:
            raise _not_found("Tender")
        if await self.runs.active_for_tender(org, tender_id) is not None:
            raise ApiError(409, "RUN_ACTIVE", "This tender already has an active run")
        if await self.runs.count_executing(org) >= MAX_EXECUTING_RUNS_PER_ORG:
            raise ApiError(429, "TOO_MANY_RUNS", "Too many concurrent runs for this organisation")
        tender_docs = await self.results.tender_documents(org, tender_id)
        tender_doc_ids = [d.id for d in tender_docs if d.kind in TENDER_KINDS]
        if not any(d.kind == "TENDER" for d in tender_docs):
            raise ApiError(409, "NO_TENDER_DOCUMENT", "Upload a tender document first")
        company_ids: list[uuid.UUID] = [d.id for d in tender_docs if d.kind not in TENDER_KINDS]
        if body.company_document_ids:
            chosen = await self.results.documents(org, body.company_document_ids)
            if len(chosen) != len(set(body.company_document_ids)):
                raise _not_found("Document")
            for doc in chosen:
                if doc.kind in TENDER_KINDS or doc.tender_id not in (None, tender_id):
                    raise ApiError(
                        422, "INVALID_COMPANY_DOCUMENT", f"{doc.id} is not a company document"
                    )
            company_ids.extend(d.id for d in chosen)
        if body.use_knowledge_base:
            company_ids.extend(d.id for d in await self.results.knowledge_base_documents(org))
        company_ids = list(dict.fromkeys(company_ids))

        run = await self.runs.create(org, tender_id, budget_from_settings())
        await self.session.commit()
        initial: TenderState = {
            "run_id": str(run.id),
            "tender_id": str(tender_id),
            "organisation_id": str(org),
            "tender_document_ids": [str(d) for d in tender_doc_ids],
            "company_document_ids": [str(d) for d in company_ids],
            "revision_count": 0,
            "sections_to_revise": [],
            "review_decision": None,
            "missing_information": [],
            "warnings": [],
            "errors": [],
        }
        await self.executor.start(org, run.id, initial)
        return run

    async def get_run(self, user: User, run_id: uuid.UUID) -> Run:
        run = await self.runs.get(user.organisation_id, run_id)
        if run is None:
            raise _not_found()
        return run

    async def run_detail(self, user: User, run_id: uuid.UUID) -> tuple[Run, list[AgentStep]]:
        run = await self.get_run(user, run_id)
        return run, await self.runs.steps(user.organisation_id, run_id)

    def _ensure_idle(self, run: Run) -> None:
        if self.executor.is_executing(run.id):
            raise ApiError(409, "RUN_BUSY", "The run is executing")

    async def review(self, user: User, run_id: uuid.UUID, body: api.ReviewRequest) -> str:
        require_writer(user)
        run = await self.get_run(user, run_id)
        if run.status != "WAITING_REVIEW":
            raise ApiError(409, "RUN_NOT_WAITING_REVIEW", "The run is not waiting for review")
        self._ensure_idle(run)
        org = user.organisation_id
        sections = list(dict.fromkeys(body.sections or []))
        if body.action == "REQUEST_CHANGES" and sections:
            proposal = await self.results.latest_proposal(org, run_id)
            known = (
                {s.section_key for s in await self.results.sections(org, proposal.id)}
                if proposal
                else set()
            )
            unknown = [s for s in sections if s not in known]
            if unknown:
                raise ApiError(422, "UNKNOWN_SECTION", "Unknown section keys", unknown)
        decision: dict[str, Any] = {
            "action": body.action,
            "sections": sections,
            "notes": body.notes,
        }
        await self.runs.add_review_action(org, run_id, user.id, body.action, decision)
        run.status = "RUNNING"
        if body.action == "REQUEST_CHANGES":
            tender = await self.results.get_tender(org, run.tender_id)
            if tender is not None:
                tender.status = "CHANGES_REQUESTED"
        await self.session.commit()
        try:
            await self.executor.resume(org, run_id, decision)
        except RunBusyError as exc:
            raise ApiError(409, "RUN_BUSY", str(exc)) from exc
        return "RUNNING"

    async def retry(self, user: User, run_id: uuid.UUID) -> str:
        require_writer(user)
        run = await self.get_run(user, run_id)
        if run.status != "FAILED":
            raise ApiError(409, "RUN_NOT_FAILED", "Only failed runs can be retried")
        self._ensure_idle(run)
        if not await self.executor.has_checkpoint(run_id):
            raise ApiError(409, "NOT_RESUMABLE", "No checkpoint exists; start a new run")
        run.status = "RUNNING"
        run.error = None
        await self.session.commit()
        await self.executor.retry(user.organisation_id, run_id)
        return "RUNNING"

    async def cancel(self, user: User, run_id: uuid.UUID) -> str:
        require_writer(user)
        run = await self.get_run(user, run_id)
        if run.status not in ACTIVE_RUN_STATUSES:
            raise ApiError(409, "RUN_NOT_ACTIVE", "Only active runs can be cancelled")
        await self.session.rollback()  # release the row before the executor updates it
        await self.executor.cancel(user.organisation_id, run_id)
        return "CANCELLED"

    # ---- results (PRD 10.4) -------------------------------------------------------------------
    async def _output(self, user: User, run_id: uuid.UUID, node: str) -> dict[str, Any] | None:
        return await self.runs.latest_output(user.organisation_id, run_id, node)

    async def _tender_requirements(self, user: User, run_id: uuid.UUID) -> TenderRequirements:
        output = await self._output(user, run_id, "tender_extract")
        if output is None:
            raise _not_available("Tender analysis")
        return TenderRequirements.model_validate(output)

    async def _evidence(self, user: User, run_id: uuid.UUID) -> CompanyEvidence:
        compliance = await self._output(user, run_id, "compliance")
        if compliance is not None and compliance.get("company_evidence") is not None:
            return CompanyEvidence.model_validate(compliance["company_evidence"])
        company = await self._output(user, run_id, "company_extract")
        if company is None:
            return CompanyEvidence(items=[])
        return CompanyEvidence.model_validate(company)

    async def analysis(self, user: User, run_id: uuid.UUID) -> api.AnalysisResponse:
        run = await self.get_run(user, run_id)
        tender = await self._tender_requirements(user, run_id)
        evidence = await self._evidence(user, run_id)
        rows = await self.results.requirements(user.organisation_id, run.tender_id, False)
        requirements = [
            api.RequirementOut(
                **requirement_to_schema(r).model_dump(),
                id=r.id,
                active=r.superseded_by is None,
                superseded_by=r.superseded_by,
            )
            for r in rows
        ]
        return api.AnalysisResponse(
            metadata=tender.metadata,
            requirements=requirements,
            evaluation_criteria=tender.evaluation_criteria,
            evidence=evidence.items,
            warnings=list(tender.extraction_warnings) + list(evidence.extraction_warnings),
        )

    async def _records(self, user: User, run_id: uuid.UUID) -> list[ComplianceRecord]:
        pairs = await self.results.compliance_records(user.organisation_id, run_id)
        codes = await self.results.evidence_codes_by_id(
            user.organisation_id, [e for rec, _ in pairs for e in rec.evidence_ids]
        )
        return records_to_schema(pairs, codes)

    async def compliance(self, user: User, run_id: uuid.UUID) -> api.ComplianceResponse:
        await self.get_run(user, run_id)
        records = await self._records(user, run_id)
        counts = Counter(r.status.value for r in records)
        return api.ComplianceResponse(
            records=records,
            summary=api.ComplianceSummary(
                compliant=counts["COMPLIANT"],
                partial=counts["PARTIAL"],
                non_compliant=counts["NON_COMPLIANT"],
                unverified=counts["UNVERIFIED"],
            ),
        )

    async def bid_decision(self, user: User, run_id: uuid.UUID) -> BidDecision:
        await self.get_run(user, run_id)
        row = await self.results.bid_decision(user.organisation_id, run_id)
        if row is None:
            raise _not_available("Bid decision")
        codes = await self.results.requirement_codes_by_id(
            user.organisation_id, row.blocking_requirements
        )
        return BidDecision(
            recommendation=row.recommendation,  # DB check constraint
            eligibility_passed=row.eligibility_passed,
            blocking_req_codes=sorted(codes[i] for i in row.blocking_requirements if i in codes),
            reasons=[str(r) for r in row.reasons],
            score=float(row.score) if row.score is not None else None,
        )

    async def missing(self, user: User, run_id: uuid.UUID) -> api.MissingListResponse:
        await self.get_run(user, run_id)
        pairs = await self.results.missing_items(user.organisation_id, run_id)
        return api.MissingListResponse(items=[missing_out(i, c) for i, c in pairs])

    async def patch_missing(
        self, user: User, item_id: uuid.UUID, body: api.MissingPatch
    ) -> api.MissingItemOut:
        require_writer(user)
        item = await self.results.get_missing_item(user.organisation_id, item_id)
        if item is None:
            raise _not_found("Missing item")
        item.resolved = body.resolved
        req_code = None
        if item.related_requirement_id is not None:
            codes = await self.results.requirement_codes_by_id(
                user.organisation_id, [item.related_requirement_id]
            )
            req_code = codes.get(item.related_requirement_id)
        out = missing_out(item, req_code)
        await self.session.commit()
        return out

    async def solution(self, user: User, run_id: uuid.UUID) -> SolutionDesign:
        await self.get_run(user, run_id)
        output = await self._output(user, run_id, "solution_design")
        if output is None:
            raise _not_available("Solution design")
        return SolutionDesign.model_validate(output)

    async def forms(self, user: User, run_id: uuid.UUID) -> api.FormsResponse:
        await self.get_run(user, run_id)
        rows = await self.results.forms(user.organisation_id, run_id)
        return api.FormsResponse(forms=[form_to_schema(r) for r in rows])

    async def proposal(self, user: User, run_id: uuid.UUID) -> api.ProposalResponse:
        await self.get_run(user, run_id)
        org = user.organisation_id
        proposal = await self.results.latest_proposal(org, run_id)
        if proposal is None:
            raise _not_available("Proposal")
        audit = await self.results.latest_audit(org, proposal.id)
        return api.ProposalResponse(
            proposal=api.ProposalInfo(version=proposal.version, status=proposal.status),
            sections=[section_out(s) for s in await self.results.sections(org, proposal.id)],
            audit_report=_audit_report(audit.passed, audit.findings) if audit else None,
        )

    async def _editable_section(
        self, user: User, run_id: uuid.UUID, section_key: str
    ) -> tuple[Run, ProposalSection]:
        run = await self.get_run(user, run_id)
        if run.status != "WAITING_REVIEW":
            raise ApiError(409, "RUN_NOT_WAITING_REVIEW", "Sections can be changed during review")
        self._ensure_idle(run)
        proposal = await self.results.latest_proposal(user.organisation_id, run_id)
        section = (
            await self.results.section(user.organisation_id, proposal.id, section_key)
            if proposal
            else None
        )
        if section is None:
            raise _not_found("Section")
        return run, section

    async def patch_section(
        self, user: User, run_id: uuid.UUID, section_key: str, body: api.SectionPatch
    ) -> api.ProposalSectionOut:
        require_writer(user)
        _, section = await self._editable_section(user, run_id, section_key)
        section.content_md = body.content_md
        section.placeholders = extract_placeholders(body.content_md)
        section.edited_by_user = True
        await self.runs.add_review_action(
            user.organisation_id, run_id, user.id, "EDIT_SECTION", {"section_key": section_key}
        )
        out = section_out(section)
        await self.session.commit()
        return out

    async def regenerate_section(
        self, user: User, run_id: uuid.UUID, section_key: str, body: api.RegenerateRequest
    ) -> str:
        require_writer(user)
        _, section = await self._editable_section(user, run_id, section_key)
        await self.runs.add_review_action(
            user.organisation_id,
            run_id,
            user.id,
            "REGENERATE_SECTION",
            {"section_key": section_key, "instructions": body.instructions},
        )
        title = section.title
        await self.session.commit()
        self.executor.spawn(
            regenerate_section_task(
                self.executor, user.organisation_id, run_id, section_key, title, body.instructions
            )
        )
        return "REGENERATING"

    # ---- exports (PRD 10.4, 11.2, 12) ---------------------------------------------------------
    async def export_docx(
        self, user: User, run_id: uuid.UUID, draft: bool, include_citations: bool
    ) -> bytes:
        run = await self.get_run(user, run_id)
        if run.status != "COMPLETED" and not draft:
            raise ApiError(
                409,
                "RUN_NOT_COMPLETED",
                "Export needs an approved run; use ?draft=true for a draft",
            )
        org = user.organisation_id
        proposal = await self.results.latest_proposal(org, run_id)
        if proposal is None:
            raise _not_available("Proposal")
        tender = await self._tender_requirements(user, run_id)
        company = await self._output(user, run_id, "company_extract") or {}
        sections = [section_to_schema(s) for s in await self.results.sections(org, proposal.id)]
        requirements = [
            requirement_to_schema(r) for r in await self.results.requirements(org, run.tender_id)
        ]
        forms = [form_to_schema(f) for f in await self.results.forms(org, run_id)]
        return build_proposal_docx(
            metadata=tender.metadata,
            company_name=company.get("company_name"),
            sections=sections,
            requirements=requirements,
            records=await self._records(user, run_id),
            forms=forms,
            draft=run.status != "COMPLETED",
            include_citations=include_citations,
        )

    async def export_xlsx(self, user: User, run_id: uuid.UUID) -> bytes:
        """Available at any run status once compliance exists (only the DOCX is gated)."""
        run = await self.get_run(user, run_id)
        org = user.organisation_id
        records = await self._records(user, run_id)
        if not records:
            raise _not_available("Compliance matrix")
        requirements = [
            requirement_to_schema(r) for r in await self.results.requirements(org, run.tender_id)
        ]
        missing = missing_to_schema(await self.results.missing_items(org, run_id))
        evidence: list[EvidenceItem] = (await self._evidence(user, run_id)).items
        return build_compliance_xlsx(
            requirements=requirements, records=records, missing=missing, evidence=evidence
        )

    async def export_audit(self, user: User, run_id: uuid.UUID) -> dict[str, Any]:
        await self.get_run(user, run_id)
        org = user.organisation_id
        proposal = await self.results.latest_proposal(org, run_id)
        audit = await self.results.latest_audit(org, proposal.id) if proposal else None
        if proposal is None or audit is None:
            raise _not_available("Audit report")
        result: dict[str, Any] = jsonable(
            {
                "run_id": run_id,
                "proposal_version": proposal.version,
                "passed": audit.passed,
                "findings": audit.findings,
                "citation_check": audit.citation_check,
                "created_at": audit.created_at.isoformat(),
            }
        )
        return result


async def regenerate_section_task(
    executor: RunExecutor,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    section_key: str,
    title: str,
    instructions: str | None,
) -> None:
    """Background regeneration of one section in the current proposal version (F-16)."""
    ctx = executor.context
    bus = executor.bus
    usage = CallUsage()
    await bus.emit(organisation_id, run_id, "node.started", REGENERATE_NODE, {"attempt": 1})
    try:
        async with ctx.sessionmaker() as session:
            runs = RunRepository(session)
            run = await runs.get(organisation_id, run_id)
            if run is None:
                return
            budget, spent = run.budget_usd, run.cost_usd
            tender_out = await runs.latest_output(organisation_id, run_id, "tender_extract")
            compliance_out = await runs.latest_output(organisation_id, run_id, "compliance") or {}
            company_out = await runs.latest_output(organisation_id, run_id, "company_extract")
            solution_out = await runs.latest_output(organisation_id, run_id, "solution_design")
        if tender_out is None:
            raise RuntimeError("tender analysis missing")
        evidence = compliance_out.get("company_evidence") or company_out or {"items": []}
        if spent > budget:
            raise BudgetExceededError(f"run cost {spent} exceeds budget {budget}")
        llm = ctx.llm_factory(usage, budget, spent)
        write_ctx = build_write_context(tender_out, evidence, solution_out)
        section = await section_writer.write_section(
            llm, section_key, title, write_ctx, str(run_id), user_instructions=instructions
        )
        async with ctx.sessionmaker() as session, session.begin():
            results = ResultsRepository(session)
            proposal = await results.latest_proposal(organisation_id, run_id)
            row = (
                await results.section(organisation_id, proposal.id, section_key)
                if proposal
                else None
            )
            if row is not None:
                row.content_md = section.content_md
                row.citations = [c.model_dump(mode="json") for c in section.citations]
                row.placeholders = list(section.placeholders)
                row.edited_by_user = False
            await RunRepository(session).add_usage(
                organisation_id, run_id, usage.tokens_in, usage.tokens_out, usage.cost_usd
            )
        await bus.emit(
            organisation_id,
            run_id,
            "node.completed",
            REGENERATE_NODE,
            {
                "duration_ms": 0,
                "tokens_in": usage.tokens_in,
                "tokens_out": usage.tokens_out,
                "cost_usd": float(usage.cost_usd),
                "summary": f"regenerated {section_key}",
            },
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.warning("section_regeneration_failed", run_id=str(run_id), error=error)
        async with ctx.sessionmaker() as session, session.begin():
            await RunRepository(session).add_usage(
                organisation_id, run_id, usage.tokens_in, usage.tokens_out, usage.cost_usd
            )
        await bus.emit(
            organisation_id,
            run_id,
            "node.failed",
            REGENERATE_NODE,
            {"error": error, "attempt": 1, "will_retry": False},
        )
