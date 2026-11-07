"""TenderIQ StateGraph (PRD 7.2) and checkpointer construction (D4)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.config import get_settings
from app.graph.nodes.audit import audit
from app.graph.nodes.base import NodeContext
from app.graph.nodes.bid_decision import bid_decision
from app.graph.nodes.company_extract import company_extract
from app.graph.nodes.compliance import compliance
from app.graph.nodes.finalize import finalize
from app.graph.nodes.form_detection import form_detection
from app.graph.nodes.human_review import human_review
from app.graph.nodes.ingest import ingest
from app.graph.nodes.solution_design import solution_design
from app.graph.nodes.tender_extract import tender_extract
from app.graph.nodes.write_sections import write_sections
from app.graph.state import TenderState

TenderGraph = CompiledStateGraph[TenderState, NodeContext, TenderState, TenderState]
NODE_ORDER = [
    "ingest",
    "tender_extract",
    "company_extract",
    "compliance",
    "bid_decision",
    "solution_design",
    "form_detection",
    "write_sections",
    "audit",
    "human_review",
    "finalize",
]


def make_route_after_audit(max_auto_revisions: int) -> Any:
    def route_after_audit(state: TenderState) -> str:
        if state["audit_report"]["passed"]:
            return "review"
        if state.get("revision_count", 0) < max_auto_revisions:
            return "revise"
        return "review"  # flagged issues go to the human

    return route_after_audit


def route_after_review(state: TenderState) -> str:
    decision = state.get("review_decision") or {}
    return "approve" if decision.get("action") == "APPROVE" else "changes"


def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None, max_auto_revisions: int | None = None
) -> TenderGraph:
    limit = get_settings().MAX_AUTO_REVISIONS if max_auto_revisions is None else max_auto_revisions
    g = StateGraph(TenderState, context_schema=NodeContext)
    g.add_node("ingest", ingest)
    g.add_node("tender_extract", tender_extract)
    g.add_node("company_extract", company_extract)
    g.add_node("compliance", compliance)
    g.add_node("bid_decision", bid_decision)
    g.add_node("solution_design", solution_design)
    g.add_node("form_detection", form_detection)
    g.add_node("write_sections", write_sections)
    g.add_node("audit", audit)
    g.add_node("human_review", human_review)
    g.add_node("finalize", finalize)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "tender_extract")
    g.add_edge("ingest", "company_extract")
    g.add_edge(["tender_extract", "company_extract"], "compliance")  # join
    g.add_edge("compliance", "bid_decision")
    g.add_edge("bid_decision", "solution_design")
    g.add_edge("bid_decision", "form_detection")
    g.add_edge(["solution_design", "form_detection"], "write_sections")  # join
    g.add_edge("write_sections", "audit")
    g.add_conditional_edges(
        "audit",
        make_route_after_audit(limit),
        {"revise": "write_sections", "review": "human_review"},
    )
    g.add_conditional_edges(
        "human_review", route_after_review, {"approve": "finalize", "changes": "write_sections"}
    )
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def memory_checkpointer() -> InMemorySaver:
    """In-process checkpointer for tests and local runs without CHECKPOINT_DB_URL."""
    return InMemorySaver()


@asynccontextmanager
async def postgres_checkpointer(conn_string: str) -> AsyncIterator[BaseCheckpointSaver[Any]]:
    """AsyncPostgresSaver on a psycopg pool; creates its tables on first use.

    psycopg's async driver needs a selector event loop (not Windows' default Proactor loop).
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo=conn_string,
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        yield saver
    finally:
        await pool.close()
