"""solution_design node (PRD 7.3): persisted in agent_steps.output only."""

from app.agents import solution_designer
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.schemas.evidence import CompanyEvidence, EvidenceCategory
from app.schemas.solution import SolutionDesign
from app.schemas.tender import ReqCategory, TenderRequirements

NAME = "solution_design"
REQ_CATEGORIES = {ReqCategory.TECHNICAL, ReqCategory.DELIVERABLE, ReqCategory.EVALUATION}
EVIDENCE_CATEGORIES = {
    EvidenceCategory.CAPABILITY,
    EvidenceCategory.PROJECT,
    EvidenceCategory.PERSONNEL,
}


async def work(call: NodeCall) -> NodeOutput:
    tender = TenderRequirements.model_validate(call.state["tender_requirements"])
    evidence = CompanyEvidence.model_validate(call.state["company_evidence"]).items
    requirements = [r for r in tender.requirements if r.category in REQ_CATEGORIES]
    relevant = [e for e in evidence if e.category in EVIDENCE_CATEGORIES]
    designed = await solution_designer.design_solution(
        call.llm, requirements, relevant, tender.metadata.scope_summary, str(call.run_id)
    )
    solution = SolutionDesign.model_validate(designed.model_dump())
    dumped = solution.model_dump(mode="json")
    return NodeOutput(
        state={"solution_design": dumped},
        output=dumped,
        summary=f"{len(solution.phases)} phases, {len(solution.capability_gaps)} capability gaps",
    )


solution_design = graph_node(NAME)(work)
