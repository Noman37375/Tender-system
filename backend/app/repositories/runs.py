"""Runs, agent steps and review actions (S-01: every query takes organisation_id).

`orphaned_runs` is the one unscoped query: the startup sweep runs before any caller exists.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentStep, ReviewAction, Run

ACTIVE_RUN_STATUSES = ("PENDING", "RUNNING", "WAITING_REVIEW")
EXECUTING_RUN_STATUSES = ("PENDING", "RUNNING")


def now() -> datetime:
    return datetime.now(UTC)


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- runs -------------------------------------------------------------------------------
    async def get(self, organisation_id: uuid.UUID, run_id: uuid.UUID) -> Run | None:
        result = await self.session.execute(
            select(Run).where(Run.id == run_id, Run.organisation_id == organisation_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self, organisation_id: uuid.UUID, tender_id: uuid.UUID, budget_usd: Decimal
    ) -> Run:
        run_id = uuid.uuid4()
        run = Run(
            id=run_id,
            organisation_id=organisation_id,
            tender_id=tender_id,
            thread_id=str(run_id),
            status="PENDING",
            budget_usd=budget_usd,
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def count_executing(self, organisation_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Run)
            .where(Run.organisation_id == organisation_id, Run.status.in_(EXECUTING_RUN_STATUSES))
        )
        return int(result.scalar_one())

    async def active_for_tender(
        self, organisation_id: uuid.UUID, tender_id: uuid.UUID
    ) -> Run | None:
        result = await self.session.execute(
            select(Run)
            .where(
                Run.organisation_id == organisation_id,
                Run.tender_id == tender_id,
                Run.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add_usage(
        self,
        organisation_id: uuid.UUID,
        run_id: uuid.UUID,
        tokens_in: int,
        tokens_out: int,
        cost_usd: Decimal,
    ) -> None:
        if not (tokens_in or tokens_out or cost_usd):
            return
        await self.session.execute(
            update(Run)
            .where(Run.id == run_id, Run.organisation_id == organisation_id)
            .values(
                tokens_in=Run.tokens_in + tokens_in,
                tokens_out=Run.tokens_out + tokens_out,
                cost_usd=Run.cost_usd + cost_usd,
            )
        )

    async def orphaned_runs(self) -> list[Run]:
        """Runs left PENDING/RUNNING by a previous process (unscoped: startup sweep only)."""
        result = await self.session.execute(
            select(Run).where(Run.status.in_(EXECUTING_RUN_STATUSES))
        )
        return list(result.scalars())

    # ---- agent steps ------------------------------------------------------------------------
    async def steps(self, organisation_id: uuid.UUID, run_id: uuid.UUID) -> list[AgentStep]:
        result = await self.session.execute(
            select(AgentStep)
            .where(AgentStep.organisation_id == organisation_id, AgentStep.run_id == run_id)
            .order_by(AgentStep.started_at, AgentStep.node, AgentStep.attempt)
        )
        return list(result.scalars())

    async def latest_step(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID, node: str, revision: int
    ) -> AgentStep | None:
        result = await self.session.execute(
            select(AgentStep)
            .where(
                AgentStep.organisation_id == organisation_id,
                AgentStep.run_id == run_id,
                AgentStep.node == node,
                AgentStep.revision == revision,
            )
            .order_by(AgentStep.attempt.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_step(self, organisation_id: uuid.UUID, step_id: uuid.UUID) -> AgentStep | None:
        result = await self.session.execute(
            select(AgentStep).where(
                AgentStep.id == step_id, AgentStep.organisation_id == organisation_id
            )
        )
        return result.scalar_one_or_none()

    async def add_step(
        self,
        organisation_id: uuid.UUID,
        run_id: uuid.UUID,
        node: str,
        revision: int,
        attempt: int,
        input_ref: dict[str, Any] | None = None,
    ) -> AgentStep:
        step = AgentStep(
            organisation_id=organisation_id,
            run_id=run_id,
            node=node,
            revision=revision,
            attempt=attempt,
            status="RUNNING",
            input_ref=input_ref,
            started_at=now(),
        )
        self.session.add(step)
        await self.session.flush()
        return step

    async def latest_output(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID, node: str
    ) -> dict[str, Any] | None:
        """Output of the newest COMPLETED step of `node` in this run."""
        result = await self.session.execute(
            select(AgentStep.output)
            .where(
                AgentStep.organisation_id == organisation_id,
                AgentStep.run_id == run_id,
                AgentStep.node == node,
                AgentStep.status == "COMPLETED",
            )
            .order_by(AgentStep.revision.desc(), AgentStep.attempt.desc())
            .limit(1)
        )
        output = result.scalar_one_or_none()
        return dict(output) if output is not None else None

    async def fail_running_steps(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID, error: str
    ) -> None:
        await self.session.execute(
            update(AgentStep)
            .where(
                AgentStep.organisation_id == organisation_id,
                AgentStep.run_id == run_id,
                AgentStep.status == "RUNNING",
            )
            .values(status="FAILED", error=error, finished_at=now())
        )

    # ---- review actions ---------------------------------------------------------------------
    async def add_review_action(
        self,
        organisation_id: uuid.UUID,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        payload: dict[str, Any] | None,
    ) -> ReviewAction:
        row = ReviewAction(
            organisation_id=organisation_id,
            run_id=run_id,
            user_id=user_id,
            action=action,
            payload=payload,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def review_actions(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[ReviewAction]:
        result = await self.session.execute(
            select(ReviewAction)
            .where(ReviewAction.organisation_id == organisation_id, ReviewAction.run_id == run_id)
            .order_by(ReviewAction.created_at)
        )
        return list(result.scalars())
