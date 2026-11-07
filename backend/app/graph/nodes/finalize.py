"""finalize node (PRD 7.3): run -> COMPLETED, tender -> APPROVED, proposal -> APPROVED."""

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Tender
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.repositories.results import ResultsRepository
from app.repositories.runs import now

NAME = "finalize"


async def work(call: NodeCall) -> NodeOutput:
    async def persist(session: AsyncSession) -> None:
        await session.execute(
            update(Run)
            .where(Run.id == call.run_id, Run.organisation_id == call.organisation_id)
            .values(status="COMPLETED", finished_at=now(), current_node=NAME, error=None)
        )
        await session.execute(
            update(Tender)
            .where(Tender.id == call.tender_id, Tender.organisation_id == call.organisation_id)
            .values(status="APPROVED")
        )
        proposal = await ResultsRepository(session).latest_proposal(
            call.organisation_id, call.run_id
        )
        if proposal is not None:
            proposal.status = "APPROVED"

    return NodeOutput(state={}, persist=persist, summary="approved")


finalize = graph_node(NAME)(work)
