"""audit node (PRD 7.3 audit): deterministic checks first, then the LLM review."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import auditor
from app.db.models import AuditReport as AuditRow
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.graph.nodes.write_sections import section_plan
from app.repositories.results import ResultsRepository, section_to_schema
from app.rules.citation_checker import deterministic_audit
from app.schemas.audit import AuditReport
from app.schemas.compliance import ComplianceRecord
from app.schemas.evidence import CompanyEvidence
from app.schemas.proposal import ProposalSection
from app.schemas.tender import TenderRequirements

NAME = "audit"


class NoProposalError(RuntimeError):
    pass


async def work(call: NodeCall) -> NodeOutput:
    tender = TenderRequirements.model_validate(call.state["tender_requirements"])
    evidence = CompanyEvidence.model_validate(call.state["company_evidence"]).items
    records = [ComplianceRecord.model_validate(r) for r in call.state.get("compliance_matrix", [])]
    async with call.session() as session:
        repo = ResultsRepository(session)
        proposal = await repo.latest_proposal(call.organisation_id, call.run_id)
        if proposal is None:
            raise NoProposalError("no proposal to audit")
        proposal_id = proposal.id
        sections: dict[str, ProposalSection] = {
            row.section_key: section_to_schema(row)
            for row in await repo.sections(call.organisation_id, proposal_id)
        }
    evidence_by_code = {e.evidence_code: e for e in evidence}
    required = [key for key, _, by_llm in section_plan(tender) if by_llm]
    automated = deterministic_audit(
        sections,
        evidence_by_code,
        tender.requirements,
        required,
        {r.req_code for r in records},
    )
    reviewed = await auditor.review(
        call.llm, sections, tender.requirements, evidence, automated, str(call.run_id)
    )
    report = AuditReport.model_validate(
        auditor.build_report(list(automated) + list(reviewed)).model_dump()
    )
    placeholder_count = sum(len(s.placeholders) for s in sections.values())
    citation_check: dict[str, Any] = {
        "findings": [f.model_dump(mode="json") for f in automated],
        "placeholder_count": placeholder_count,
    }

    async def persist(session: AsyncSession) -> None:
        repo = ResultsRepository(session)
        await repo.delete_audits(call.organisation_id, proposal_id)
        session.add(
            AuditRow(
                organisation_id=call.organisation_id,
                proposal_id=proposal_id,
                passed=report.passed,
                findings=[f.model_dump(mode="json") for f in report.findings],
                citation_check=citation_check,
            )
        )
        latest = await repo.latest_proposal(call.organisation_id, call.run_id)
        if latest is not None and latest.id == proposal_id:
            latest.status = "AUDIT_PASSED" if report.passed else "AUDIT_FAILED"

    blockers = sum(1 for f in report.findings if f.severity == "BLOCKER")
    majors = sum(1 for f in report.findings if f.severity == "MAJOR")
    dumped = report.model_dump(mode="json")
    return NodeOutput(
        state={"audit_report": dumped, "sections_to_revise": list(report.sections_to_revise)},
        persist=persist,
        output={**dumped, "placeholder_count": placeholder_count},
        summary=f"passed={report.passed} blockers={blockers} majors={majors}",
        events=[
            (
                "audit.result",
                {"passed": report.passed, "blocker_count": blockers, "major_count": majors},
            )
        ],
    )


audit = graph_node(NAME)(work)
