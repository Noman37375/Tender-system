"""Shared node contract (PRD 7.3) and the runtime context handed to every node.

Every node is a `work` function wrapped by `graph_node`. The wrapper performs the 7 steps:

1. write the `agent_steps` RUNNING row (revision = runs.revision_count, attempt = previous + 1)
2. emit `node.started`
3. call `work` (it loads from the DB and calls the agent / rules functions)
4. validation happens inside `work` (Pydantic models; invariants)
5. persist in ONE transaction: `work`'s persist callback (which first deletes this run's prior
   rows for the node + revision) + the step's COMPLETED update + the run's usage totals
6. emit `node.completed` (or mark the step FAILED and emit `node.failed`, then re-raise)
7. return only the state keys `work` owns

Business logic stays in app/agents, app/rules and app/ingestion. Nodes only orchestrate.
"""

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol

import structlog
from langgraph.errors import GraphBubbleUp
from langgraph.runtime import Runtime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import AgentStep
from app.graph.events import EventBus
from app.graph.state import TenderState
from app.llm.adapter import BudgetExceededError, CallUsage, LLMClient
from app.repositories.results import jsonable
from app.repositories.runs import RunRepository, now

log = structlog.get_logger(__name__)


class LLMFactory(Protocol):
    def __call__(self, usage: CallUsage, budget_usd: Decimal, spent_usd: Decimal) -> LLMClient: ...


def default_llm_factory(usage: CallUsage, budget_usd: Decimal, spent_usd: Decimal) -> LLMClient:
    """Real provider client (built lazily so tests never need provider keys)."""
    from app.llm.factory import build_llm_client  # type: ignore[import-not-found,unused-ignore]

    client: LLMClient = build_llm_client(usage=usage, budget_usd=budget_usd, spent_usd=spent_usd)
    return client


@dataclass
class NodeContext:
    """Runtime context (not checkpointed): DB, event bus, LLM factory, limits."""

    sessionmaker: async_sessionmaker[AsyncSession]
    bus: EventBus
    llm_factory: LLMFactory = default_llm_factory
    llm_concurrency: int = 4
    today: Callable[[], date] = field(default=lambda: datetime.now(UTC).date())


class RunCancelledError(RuntimeError):
    pass


@dataclass
class NodeCall:
    """What a node's work function receives."""

    name: str
    ctx: NodeContext
    state: TenderState
    run_id: uuid.UUID
    organisation_id: uuid.UUID
    tender_id: uuid.UUID
    revision: int
    attempt: int
    usage: CallUsage
    llm_builder: Callable[[], LLMClient]
    _llm: LLMClient | None = field(default=None, init=False, repr=False)

    @property
    def llm(self) -> LLMClient:
        """Built on first use, so nodes without LLM calls never construct a client."""
        if self._llm is None:
            self._llm = self.llm_builder()
        return self._llm

    def session(self) -> AsyncSession:
        return self.ctx.sessionmaker()

    async def progress(self, message: str, done: int, total: int) -> None:
        await self.ctx.bus.emit(
            self.organisation_id,
            self.run_id,
            "node.progress",
            self.name,
            {"message": message, "done": done, "total": total},
        )


PersistFn = Callable[[AsyncSession], Awaitable[None]]


@dataclass
class NodeOutput:
    state: dict[str, Any]
    persist: PersistFn | None = None
    output: dict[str, Any] | None = None  # agent_steps.output
    summary: str = ""
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


NodeWork = Callable[[NodeCall], Awaitable[NodeOutput]]
RevisionFn = Callable[[TenderState], int]


class GraphNodeFn(Protocol):
    """Shape LangGraph expects for a node that takes the runtime context."""

    def __call__(
        self, state: TenderState, *, runtime: Runtime[NodeContext]
    ) -> Awaitable[dict[str, Any]]: ...



@dataclass
class _Started:
    budget_usd: Decimal
    cost_usd: Decimal
    step_id: uuid.UUID
    revision: int
    attempt: int
    resumed: bool


async def _start_step(
    ctx: NodeContext,
    name: str,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    revision_from: RevisionFn | None,
    state: TenderState,
) -> _Started:
    async with ctx.sessionmaker() as session, session.begin():
        repo = RunRepository(session)
        run = await repo.get(organisation_id, run_id)
        if run is None:
            raise RuntimeError(f"run {run_id} not found")
        if run.status == "CANCELLED":
            raise RunCancelledError("run was cancelled")
        if revision_from is not None:
            run.revision_count = revision_from(state)
        revision = run.revision_count
        run.current_node = name
        latest = await repo.latest_step(organisation_id, run_id, name, revision)
        if latest is not None and latest.status == "RUNNING":
            # interrupted node (human_review) resuming, or a step orphaned by a crash
            step: AgentStep = latest
            resumed = True
        else:
            attempt = (latest.attempt + 1) if latest is not None else 1
            step = await repo.add_step(organisation_id, run_id, name, revision, attempt)
            resumed = False
        return _Started(run.budget_usd, run.cost_usd, step.id, revision, step.attempt, resumed)


async def _finish_step(
    ctx: NodeContext,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    step_id: uuid.UUID,
    usage: CallUsage,
    *,
    status: str,
    out: "NodeOutput | None" = None,
    error: str | None = None,
) -> None:
    async with ctx.sessionmaker() as session, session.begin():
        if out is not None and out.persist is not None:
            await out.persist(session)
        output = out.output if out is not None else None
        repo = RunRepository(session)
        step = await repo.get_step(organisation_id, step_id)
        if step is not None:
            step.status = status
            step.output = jsonable(output) if output is not None else None
            step.error = error
            step.tokens_in = usage.tokens_in
            step.tokens_out = usage.tokens_out
            step.cost_usd = usage.cost_usd
            step.model = ",".join(dict.fromkeys(usage.models)) or None
            step.prompt_version = ",".join(dict.fromkeys(usage.prompt_versions)) or None
            step.finished_at = now()
        await repo.add_usage(
            organisation_id, run_id, usage.tokens_in, usage.tokens_out, usage.cost_usd
        )


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, BudgetExceededError):
        return f"BUDGET_EXCEEDED: {exc}" if str(exc) else "BUDGET_EXCEEDED"
    return f"{type(exc).__name__}: {exc}"


async def execute_node(
    name: str,
    work: NodeWork,
    state: TenderState,
    ctx: NodeContext,
    revision_from: RevisionFn | None = None,
) -> dict[str, Any]:
    organisation_id = uuid.UUID(state["organisation_id"])
    run_id = uuid.UUID(state["run_id"])
    started = await _start_step(ctx, name, organisation_id, run_id, revision_from, state)
    if not started.resumed:
        await ctx.bus.emit(
            organisation_id, run_id, "node.started", name, {"attempt": started.attempt}
        )
    usage = CallUsage()
    t0 = time.monotonic()
    log.info("node_started", run_id=str(run_id), node=name, attempt=started.attempt)
    try:
        if started.cost_usd > started.budget_usd:
            raise BudgetExceededError(
                f"run cost {started.cost_usd} exceeds budget {started.budget_usd}"
            )
        call = NodeCall(
            name=name,
            ctx=ctx,
            state=state,
            run_id=run_id,
            organisation_id=organisation_id,
            tender_id=uuid.UUID(state["tender_id"]),
            revision=started.revision,
            attempt=started.attempt,
            usage=usage,
            llm_builder=lambda: ctx.llm_factory(usage, started.budget_usd, started.cost_usd),
        )
        out = await work(call)
        await _finish_step(
            ctx,
            organisation_id,
            run_id,
            started.step_id,
            usage,
            status="COMPLETED",
            out=out,
        )
    except GraphBubbleUp:
        raise  # interrupt(): the step stays RUNNING until the run is resumed
    except Exception as exc:
        error = _error_text(exc)
        log.warning("node_failed", run_id=str(run_id), node=name, error=error)
        try:
            await _finish_step(
                ctx, organisation_id, run_id, started.step_id, usage, status="FAILED", error=error
            )
        finally:
            await ctx.bus.emit(
                organisation_id,
                run_id,
                "node.failed",
                name,
                {"error": error, "attempt": started.attempt, "will_retry": False},
            )
        raise
    duration_ms = int((time.monotonic() - t0) * 1000)
    await ctx.bus.emit(
        organisation_id,
        run_id,
        "node.completed",
        name,
        {
            "duration_ms": duration_ms,
            "tokens_in": usage.tokens_in,
            "tokens_out": usage.tokens_out,
            "cost_usd": float(usage.cost_usd),
            "summary": out.summary,
        },
    )
    for type_, payload in out.events:
        await ctx.bus.emit(organisation_id, run_id, type_, name, payload)
    return out.state


def graph_node(
    name: str, revision_from: RevisionFn | None = None
) -> Callable[[NodeWork], GraphNodeFn]:
    """Wrap a work function in the node contract; the result is added to the StateGraph."""

    def decorate(work: NodeWork) -> GraphNodeFn:
        async def node(state: TenderState, *, runtime: Runtime[NodeContext]) -> dict[str, Any]:
            return await execute_node(name, work, state, runtime.context, revision_from)

        node.__name__ = name
        node.__qualname__ = name
        return node

    return decorate


def parse_deadline(value: str | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
