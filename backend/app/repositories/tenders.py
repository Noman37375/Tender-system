"""Tender data access. Every query is filtered by the caller's organisation_id (S-01)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run, Tender


class TenderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self, organisation_id: uuid.UUID, title: str | None, created_by: uuid.UUID | None
    ) -> Tender:
        tender = Tender(organisation_id=organisation_id, title=title, created_by=created_by)
        self.session.add(tender)
        await self.session.flush()
        await self.session.refresh(tender)
        return tender

    async def get(self, organisation_id: uuid.UUID, tender_id: uuid.UUID) -> Tender | None:
        result = await self.session.execute(
            select(Tender).where(Tender.id == tender_id, Tender.organisation_id == organisation_id)
        )
        return result.scalar_one_or_none()

    async def list(
        self, organisation_id: uuid.UUID, status: str | None, offset: int, limit: int
    ) -> tuple[list[Tender], int]:
        conditions = [Tender.organisation_id == organisation_id]
        if status is not None:
            conditions.append(Tender.status == status)
        total = await self.session.scalar(
            select(func.count()).select_from(Tender).where(*conditions)
        )
        result = await self.session.execute(
            select(Tender)
            .where(*conditions)
            .order_by(Tender.created_at.desc(), Tender.id)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def count_by_status(self, organisation_id: uuid.UUID) -> dict[str, int]:
        result = await self.session.execute(
            select(Tender.status, func.count())
            .where(Tender.organisation_id == organisation_id)
            .group_by(Tender.status)
        )
        return {status: int(count) for status, count in result.all()}

    async def latest_run(self, organisation_id: uuid.UUID, tender_id: uuid.UUID) -> Run | None:
        result = await self.session.execute(
            select(Run)
            .where(Run.organisation_id == organisation_id, Run.tender_id == tender_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()
