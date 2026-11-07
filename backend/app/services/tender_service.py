import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, Run, Tender, User
from app.db.models.documents import TENDER_STATUSES
from app.errors import ApiError
from app.repositories.documents import DocumentRepository
from app.repositories.tenders import TenderRepository


@dataclass(frozen=True)
class TenderDetail:
    tender: Tender
    documents: list[Document]
    latest_run: Run | None


@dataclass(frozen=True)
class DashboardStats:
    tenders: int
    awaiting_review: int
    approved: int


class TenderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tenders = TenderRepository(session)
        self.documents = DocumentRepository(session)

    async def create(self, user: User, title: str | None) -> Tender:
        tender = await self.tenders.create(user.organisation_id, title, user.id)
        await self.session.commit()
        return tender

    async def get_or_404(self, organisation_id: uuid.UUID, tender_id: uuid.UUID) -> Tender:
        tender = await self.tenders.get(organisation_id, tender_id)
        if tender is None:
            raise ApiError(404, "NOT_FOUND", "Tender not found")
        return tender

    async def list(
        self, organisation_id: uuid.UUID, status: str | None, page: int, page_size: int
    ) -> tuple[list[Tender], int]:
        if status is not None and status not in TENDER_STATUSES:
            raise ApiError(
                422, "VALIDATION_ERROR", "Unknown tender status", {"allowed": TENDER_STATUSES}
            )
        return await self.tenders.list(organisation_id, status, (page - 1) * page_size, page_size)

    async def detail(self, organisation_id: uuid.UUID, tender_id: uuid.UUID) -> TenderDetail:
        tender = await self.get_or_404(organisation_id, tender_id)
        documents = await self.documents.list_for_tender(organisation_id, tender_id)
        latest_run = await self.tenders.latest_run(organisation_id, tender_id)
        return TenderDetail(tender, documents, latest_run)

    async def dashboard_stats(self, organisation_id: uuid.UUID) -> DashboardStats:
        counts = await self.tenders.count_by_status(organisation_id)
        return DashboardStats(
            tenders=sum(counts.values()),
            awaiting_review=counts.get("AWAITING_REVIEW", 0),
            approved=counts.get("APPROVED", 0),
        )
