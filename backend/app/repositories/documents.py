"""Document, page and chunk data access. Every query is filtered by organisation_id (S-01)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document, DocumentPage


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)
        return document

    async def get(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        result = await self.session.execute(
            select(Document).where(
                Document.id == document_id, Document.organisation_id == organisation_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_tender(
        self, organisation_id: uuid.UUID, tender_id: uuid.UUID
    ) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.organisation_id == organisation_id, Document.tender_id == tender_id)
            .order_by(Document.created_at, Document.id)
        )
        return list(result.scalars().all())

    async def list_knowledge_base(self, organisation_id: uuid.UUID) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.organisation_id == organisation_id, Document.tender_id.is_(None))
            .order_by(Document.created_at.desc(), Document.id)
        )
        return list(result.scalars().all())

    async def count_for_tender(self, organisation_id: uuid.UUID, tender_id: uuid.UUID) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.organisation_id == organisation_id, Document.tender_id == tender_id)
        )
        return int(total or 0)

    async def max_addendum_seq(self, organisation_id: uuid.UUID, tender_id: uuid.UUID) -> int:
        value = await self.session.scalar(
            select(func.max(Document.addendum_seq)).where(
                Document.organisation_id == organisation_id, Document.tender_id == tender_id
            )
        )
        return int(value or 0)

    async def delete(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> None:
        """Pages, chunks and evidence items go with it through ON DELETE CASCADE."""
        await self.session.execute(
            delete(Document).where(
                Document.id == document_id, Document.organisation_id == organisation_id
            )
        )

    # pages ---------------------------------------------------------------------------------

    async def get_page(
        self, organisation_id: uuid.UUID, document_id: uuid.UUID, page_no: int
    ) -> DocumentPage | None:
        result = await self.session.execute(
            select(DocumentPage).where(
                DocumentPage.organisation_id == organisation_id,
                DocumentPage.document_id == document_id,
                DocumentPage.page_no == page_no,
            )
        )
        return result.scalar_one_or_none()

    async def count_pages(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(DocumentPage)
            .where(
                DocumentPage.organisation_id == organisation_id,
                DocumentPage.document_id == document_id,
            )
        )
        return int(total or 0)

    async def replace_pages_and_chunks(
        self,
        organisation_id: uuid.UUID,
        document_id: uuid.UUID,
        pages: Sequence[dict[str, Any]],
        chunks: Sequence[dict[str, Any]],
    ) -> None:
        """Drop earlier extraction output for the document and write the new one."""
        await self.session.execute(
            delete(Chunk).where(
                Chunk.organisation_id == organisation_id, Chunk.document_id == document_id
            )
        )
        await self.session.execute(
            delete(DocumentPage).where(
                DocumentPage.organisation_id == organisation_id,
                DocumentPage.document_id == document_id,
            )
        )
        self.session.add_all(
            DocumentPage(organisation_id=organisation_id, document_id=document_id, **p)
            for p in pages
        )
        self.session.add_all(
            Chunk(organisation_id=organisation_id, document_id=document_id, **c) for c in chunks
        )
        await self.session.flush()

    # chunks --------------------------------------------------------------------------------

    async def chunks_without_embedding(
        self, organisation_id: uuid.UUID, document_id: uuid.UUID
    ) -> list[Chunk]:
        result = await self.session.execute(
            select(Chunk)
            .where(
                Chunk.organisation_id == organisation_id,
                Chunk.document_id == document_id,
                Chunk.embedding.is_(None),
            )
            .order_by(Chunk.page_start, Chunk.id)
        )
        return list(result.scalars().all())

    async def set_embedding(
        self, organisation_id: uuid.UUID, chunk_id: uuid.UUID, embedding: list[float]
    ) -> None:
        await self.session.execute(
            update(Chunk)
            .where(Chunk.id == chunk_id, Chunk.organisation_id == organisation_id)
            .values(embedding=embedding)
        )

    async def list_chunks(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> list[Chunk]:
        result = await self.session.execute(
            select(Chunk)
            .where(Chunk.organisation_id == organisation_id, Chunk.document_id == document_id)
            .order_by(Chunk.page_start, Chunk.page_end, Chunk.id)
        )
        return list(result.scalars().all())
