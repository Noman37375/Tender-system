"""Run event bus (PRD 10.5).

Every event is written to `run_events` FIRST (its id becomes the SSE `id:`), then handed to the
in-process subscribers of that run. Publishing never blocks a run: a slow subscriber whose queue
is full simply misses live events and catches up from `run_events` on reconnect, and a database
error while recording an event is logged instead of breaking the node that emitted it.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RunEvent

log = structlog.get_logger(__name__)

TERMINAL_EVENTS = frozenset({"run.completed", "run.failed", "run.cancelled"})
SUBSCRIBER_QUEUE_SIZE = 1000


@dataclass(frozen=True)
class BusEvent:
    id: int
    run_id: uuid.UUID
    type: str
    node: str | None
    ts: datetime
    payload: dict[str, Any] = field(default_factory=dict)

    def data(self) -> dict[str, Any]:
        """The SSE `data:` object (PRD 10.5)."""
        return {
            "run_id": str(self.run_id),
            "node": self.node,
            "ts": self.ts.isoformat(),
            "payload": self.payload,
        }

    @classmethod
    def from_row(cls, row: RunEvent) -> "BusEvent":
        return cls(row.id, row.run_id, row.type, row.node, row.ts, dict(row.payload or {}))


class EventBus:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[BusEvent]]] = {}

    async def emit(
        self,
        organisation_id: uuid.UUID,
        run_id: uuid.UUID,
        type_: str,
        node: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> BusEvent | None:
        try:
            async with self._sessionmaker() as session, session.begin():
                row = RunEvent(
                    organisation_id=organisation_id,
                    run_id=run_id,
                    type=type_,
                    node=node,
                    payload=payload or {},
                    ts=datetime.now(UTC),
                )
                session.add(row)
                await session.flush()
                event = BusEvent.from_row(row)
        except Exception as exc:  # recording must never break a run
            log.warning("run_event_write_failed", run_id=str(run_id), type=type_, error=repr(exc))
            return None
        self.publish(event)
        return event

    def publish(self, event: BusEvent) -> None:
        for queue in list(self._subscribers.get(event.run_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("run_event_subscriber_full", run_id=str(event.run_id))

    def subscribe(self, run_id: uuid.UUID) -> asyncio.Queue[BusEvent]:
        queue: asyncio.Queue[BusEvent] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: uuid.UUID, queue: asyncio.Queue[BusEvent]) -> None:
        queues = self._subscribers.get(run_id)
        if queues is None:
            return
        queues.discard(queue)
        if not queues:
            del self._subscribers[run_id]

    def subscriber_count(self, run_id: uuid.UUID) -> int:
        return len(self._subscribers.get(run_id, ()))

    async def replay(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID, after_id: int
    ) -> list[BusEvent]:
        """Stored events of a run with id > after_id, oldest first (Last-Event-ID replay)."""
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(RunEvent)
                .where(
                    RunEvent.organisation_id == organisation_id,
                    RunEvent.run_id == run_id,
                    RunEvent.id > after_id,
                )
                .order_by(RunEvent.id)
            )
            return [BusEvent.from_row(r) for r in rows.scalars()]
