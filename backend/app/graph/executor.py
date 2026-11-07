"""In-process run executor (D3): runs the graph as asyncio tasks.

Run status: PENDING -> RUNNING -> WAITING_REVIEW -> (RUNNING ->) COMPLETED, or FAILED / CANCELLED.
Tender status: PROCESSING while running, AWAITING_REVIEW at the gate, CHANGES_REQUESTED after a
change request (set by the review service), APPROVED by `finalize`, FAILED on failure, DRAFT
after a cancel.

- start: new thread (thread_id = run id) from the initial state
- resume: `Command(resume=decision)` continues the human_review interrupt
- retry: `None` input continues from the last checkpoint; only unfinished nodes run again
- cancel: cancels the task and marks the run CANCELLED
- startup sweep: runs left PENDING/RUNNING by a dead process become FAILED
  ("interrupted by restart") so they can be retried from their checkpoint
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from decimal import Decimal
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.db.models import Tender
from app.graph.builder import TenderGraph, build_graph, memory_checkpointer, postgres_checkpointer
from app.graph.events import EventBus
from app.graph.nodes.base import LLMFactory, NodeContext, default_llm_factory
from app.graph.state import TenderState
from app.llm.adapter import BudgetExceededError
from app.repositories.runs import RunRepository, now

log = structlog.get_logger(__name__)

RESTART_ERROR = "interrupted by restart"


class RunBusyError(RuntimeError):
    """The run already has an executing task."""


class RunExecutor:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        bus: EventBus,
        checkpointer: BaseCheckpointSaver[Any],
        llm_factory: LLMFactory = default_llm_factory,
        max_auto_revisions: int | None = None,
        llm_concurrency: int | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.bus = bus
        self.graph: TenderGraph = build_graph(checkpointer, max_auto_revisions)
        self.context = NodeContext(
            sessionmaker=sessionmaker,
            bus=bus,
            llm_factory=llm_factory,
            llm_concurrency=llm_concurrency or get_settings().LLM_CONCURRENCY,
        )
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._background: set[asyncio.Task[Any]] = set()

    # ---- public API ---------------------------------------------------------------------------
    @staticmethod
    def config(run_id: uuid.UUID) -> RunnableConfig:
        return {"configurable": {"thread_id": str(run_id)}}

    def is_executing(self, run_id: uuid.UUID) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    async def start(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID, initial_state: TenderState
    ) -> None:
        self._launch(
            run_id,
            self._drive(
                organisation_id,
                run_id,
                initial_state,
                emit_started=True,
                tender_status="PROCESSING",
            ),
        )

    async def resume(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID, decision: dict[str, Any]
    ) -> None:
        self._launch(
            run_id,
            self._drive(organisation_id, run_id, Command(resume=decision), emit_started=False),
        )

    async def retry(self, organisation_id: uuid.UUID, run_id: uuid.UUID) -> None:
        self._launch(
            run_id,
            self._drive(
                organisation_id, run_id, None, emit_started=False, tender_status="PROCESSING"
            ),
        )

    async def has_checkpoint(self, run_id: uuid.UUID) -> bool:
        snapshot = await self.graph.aget_state(self.config(run_id))
        return bool(snapshot.values)

    async def state(self, run_id: uuid.UUID) -> dict[str, Any]:
        snapshot = await self.graph.aget_state(self.config(run_id))
        return dict(snapshot.values)

    async def cancel(self, organisation_id: uuid.UUID, run_id: uuid.UUID) -> None:
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait([task])
        async with self.sessionmaker() as session, session.begin():
            repo = RunRepository(session)
            run = await repo.get(organisation_id, run_id)
            if run is None:
                return
            run.status = "CANCELLED"
            run.finished_at = now()
            await repo.fail_running_steps(organisation_id, run_id, "cancelled")
            await _set_tender_status(session, organisation_id, run.tender_id, "DRAFT")
        await self.bus.emit(organisation_id, run_id, "run.cancelled", None, {})

    async def wait(self, run_id: uuid.UUID) -> None:
        """Wait for the run's current task (tests, graceful shutdown)."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.wait([task])

    async def wait_background(self) -> None:
        if self._background:
            await asyncio.wait(list(self._background))

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        """Fire-and-forget background work (e.g. section regeneration); keeps a reference."""
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def aclose(self) -> None:
        for task in list(self._tasks.values()) + list(self._background):
            task.cancel()
        pending = list(self._tasks.values()) + list(self._background)
        if pending:
            await asyncio.wait(pending)

    # ---- internals ----------------------------------------------------------------------------
    def _launch(self, run_id: uuid.UUID, coro: Coroutine[Any, Any, None]) -> None:
        if self.is_executing(run_id):
            coro.close()
            raise RunBusyError(f"run {run_id} is already executing")
        task = asyncio.create_task(coro, name=f"run-{run_id}")
        self._tasks[run_id] = task

        def _forget(t: asyncio.Task[None]) -> None:
            if self._tasks.get(run_id) is t:
                del self._tasks[run_id]

        task.add_done_callback(_forget)

    async def _drive(
        self,
        organisation_id: uuid.UUID,
        run_id: uuid.UUID,
        graph_input: Any,
        *,
        emit_started: bool,
        tender_status: str | None = None,
    ) -> None:
        try:
            async with self.sessionmaker() as session, session.begin():
                run = await RunRepository(session).get(organisation_id, run_id)
                if run is None:
                    return
                run.status = "RUNNING"
                run.error = None
                run.finished_at = None
                run.started_at = run.started_at or now()
                if tender_status is not None:
                    await _set_tender_status(session, organisation_id, run.tender_id, tender_status)
            if emit_started:
                await self.bus.emit(organisation_id, run_id, "run.started", None, {})
            await self.graph.ainvoke(graph_input, self.config(run_id), context=self.context)
            snapshot = await self.graph.aget_state(self.config(run_id))
            if snapshot.next:
                audit_passed = bool((snapshot.values.get("audit_report") or {}).get("passed"))
                await self._set_status(organisation_id, run_id, "WAITING_REVIEW", "AWAITING_REVIEW")
                await self.bus.emit(
                    organisation_id,
                    run_id,
                    "run.waiting_review",
                    "human_review",
                    {"audit_passed": audit_passed},
                )
            else:
                await self._set_status(organisation_id, run_id, "COMPLETED", None, finished=True)
                await self.bus.emit(organisation_id, run_id, "run.completed", None, {})
        except asyncio.CancelledError:
            raise
        except BudgetExceededError as exc:
            detail = str(exc)
            await self._fail(
                organisation_id,
                run_id,
                f"BUDGET_EXCEEDED: {detail}" if detail else "BUDGET_EXCEEDED",
            )
        except Exception as exc:
            await self._fail(organisation_id, run_id, f"{type(exc).__name__}: {exc}")

    async def _set_status(
        self,
        organisation_id: uuid.UUID,
        run_id: uuid.UUID,
        status: str,
        tender_status: str | None,
        *,
        finished: bool = False,
        error: str | None = None,
    ) -> None:
        async with self.sessionmaker() as session, session.begin():
            run = await RunRepository(session).get(organisation_id, run_id)
            if run is None:
                return
            run.status = status
            run.error = error
            if finished and run.finished_at is None:
                run.finished_at = now()
            if tender_status is not None:
                await _set_tender_status(session, organisation_id, run.tender_id, tender_status)

    async def _fail(self, organisation_id: uuid.UUID, run_id: uuid.UUID, error: str) -> None:
        log.warning("run_failed", run_id=str(run_id), error=error)
        await self._set_status(
            organisation_id, run_id, "FAILED", "FAILED", finished=True, error=error
        )
        await self.bus.emit(organisation_id, run_id, "run.failed", None, {"error": error})


async def _set_tender_status(
    session: AsyncSession, organisation_id: uuid.UUID, tender_id: uuid.UUID, status: str
) -> None:
    await session.execute(
        update(Tender)
        .where(Tender.id == tender_id, Tender.organisation_id == organisation_id)
        .values(status=status)
    )


async def mark_orphaned_runs(sessionmaker: async_sessionmaker[AsyncSession], bus: EventBus) -> int:
    """Startup sweep: no task survives a restart, so PENDING/RUNNING runs are orphans."""
    orphans: list[tuple[uuid.UUID, uuid.UUID]] = []
    async with sessionmaker() as session, session.begin():
        repo = RunRepository(session)
        for run in await repo.orphaned_runs():
            run.status = "FAILED"
            run.error = RESTART_ERROR
            run.finished_at = now()
            await repo.fail_running_steps(run.organisation_id, run.id, RESTART_ERROR)
            await _set_tender_status(session, run.organisation_id, run.tender_id, "FAILED")
            orphans.append((run.organisation_id, run.id))
    for organisation_id, run_id in orphans:
        await bus.emit(organisation_id, run_id, "run.failed", None, {"error": RESTART_ERROR})
    return len(orphans)


# ---- process-wide executor ----------------------------------------------------------------------
_executor: RunExecutor | None = None
_exit_stack: AsyncExitStack | None = None
_lock: asyncio.Lock | None = None


async def get_executor() -> RunExecutor:
    """The process-wide executor; Postgres checkpointer when CHECKPOINT_DB_URL is set."""
    global _executor, _exit_stack, _lock
    if _executor is not None:
        return _executor
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        if _executor is None:
            from app.db.session import get_sessionmaker

            settings = get_settings()
            stack = AsyncExitStack()
            checkpointer: BaseCheckpointSaver[Any]
            if settings.CHECKPOINT_DB_URL:
                checkpointer = await stack.enter_async_context(
                    postgres_checkpointer(settings.CHECKPOINT_DB_URL)
                )
            else:
                log.warning("checkpointer_in_memory", reason="CHECKPOINT_DB_URL not set")
                checkpointer = memory_checkpointer()
            sessionmaker = get_sessionmaker()
            _executor = RunExecutor(
                sessionmaker=sessionmaker, bus=EventBus(sessionmaker), checkpointer=checkpointer
            )
            _exit_stack = stack
    return _executor


def set_executor(executor: RunExecutor | None) -> None:
    """Install an executor (tests inject one with fakes and an in-memory checkpointer)."""
    global _executor
    _executor = executor


async def shutdown_executor() -> None:
    global _executor, _exit_stack
    if _executor is not None:
        await _executor.aclose()
    if _exit_stack is not None:
        await _exit_stack.aclose()
    _executor, _exit_stack = None, None


@asynccontextmanager
async def executor_lifespan(_app: Any) -> AsyncIterator[None]:
    """Mounted through the runs router: sweep orphaned runs at startup, close on shutdown."""
    try:
        executor = await get_executor()
        swept = await mark_orphaned_runs(executor.sessionmaker, executor.bus)
        if swept:
            log.warning("orphaned_runs_failed", count=swept)
    except Exception as exc:  # the API must still start (e.g. DB not ready yet)
        log.error("executor_startup_failed", error=repr(exc))
    try:
        yield
    finally:
        await shutdown_executor()


def budget_from_settings() -> Decimal:
    return Decimal(str(get_settings().RUN_BUDGET_USD))
