"""bid_decision node (PRD 7.3 bid_decision): rules first, optional LLM wording of reasons.

NO_BID never stops the graph (PRD 7.2): the decision is stored, a warning is added, and the run
continues so the user can override or cancel.
"""

import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import bid_reasons
from app.db.models import BidDecision as BidDecisionRow
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.llm.adapter import BudgetExceededError
from app.repositories.results import ResultsRepository
from app.rules import bid_decision as bid_rules
from app.schemas.compliance import BidDecision, ComplianceRecord
from app.schemas.tender import TenderRequirements

NAME = "bid_decision"


async def work(call: NodeCall) -> NodeOutput:
    requirements = TenderRequirements.model_validate(call.state["tender_requirements"]).requirements
    records = [ComplianceRecord.model_validate(r) for r in call.state.get("compliance_matrix", [])]
    decision = BidDecision.model_validate(bid_rules.decide(requirements, records).model_dump())
    warnings: list[str] = []
    try:
        reasons = await bid_reasons.explain(call.llm, decision, records, str(call.run_id))
        if reasons:
            decision = decision.model_copy(update={"reasons": list(reasons)})
    except BudgetExceededError:
        raise
    except Exception as exc:  # wording is optional; the rule-generated reasons stand
        warnings.append(f"bid reasons wording skipped: {type(exc).__name__}")
    if decision.recommendation == "NO_BID":
        warnings.append(
            "NO_BID recommended; blocking requirements: " + ", ".join(decision.blocking_req_codes)
        )
    req_ids = await _requirement_ids(call)

    async def persist(session: AsyncSession) -> None:
        repo = ResultsRepository(session)
        await repo.delete_run_rows(BidDecisionRow, call.organisation_id, call.run_id)
        await session.flush()
        session.add(
            BidDecisionRow(
                organisation_id=call.organisation_id,
                run_id=call.run_id,
                recommendation=decision.recommendation,
                eligibility_passed=decision.eligibility_passed,
                blocking_requirements=[
                    req_ids[c] for c in decision.blocking_req_codes if c in req_ids
                ],
                reasons=decision.reasons,
                score=Decimal(str(decision.score)) if decision.score is not None else None,
            )
        )

    dumped = decision.model_dump(mode="json")
    return NodeOutput(
        state={"bid_decision": dumped, "warnings": warnings},
        persist=persist,
        output=dumped,
        summary=decision.recommendation,
    )


async def _requirement_ids(call: NodeCall) -> dict[str, uuid.UUID]:
    async with call.session() as session:
        rows = await ResultsRepository(session).requirements(call.organisation_id, call.tender_id)
    return {r.req_code: r.id for r in rows}


bid_decision = graph_node(NAME)(work)
