"""human_review node (PRD 7.3): pauses the run with interrupt() until POST /runs/{id}/review.

The review_actions row is written by the review endpoint (it knows the user), before resuming.
"""

from langgraph.types import interrupt

from app.graph.nodes.base import NodeCall, NodeOutput, graph_node

NAME = "human_review"


async def work(call: NodeCall) -> NodeOutput:
    audit = call.state.get("audit_report") or {}
    decision = interrupt(
        {
            "type": "review_required",
            "run_id": call.state["run_id"],
            "audit_passed": bool(audit.get("passed", False)),
        }
    )
    if not isinstance(decision, dict) or decision.get("action") not in (
        "APPROVE",
        "REQUEST_CHANGES",
    ):
        raise ValueError(f"invalid review decision: {decision!r}")
    return NodeOutput(
        state={"review_decision": decision},
        output={"action": decision["action"]},
        summary=str(decision["action"]),
    )


human_review = graph_node(NAME)(work)
