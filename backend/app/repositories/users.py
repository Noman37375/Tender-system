"""User and organisation data access.

Lookups that serve an authenticated caller take organisation_id and filter by it (S-01).
`get_by_email` is the one unscoped lookup: login happens before the organisation is known.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Organisation, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def get(self, organisation_id: uuid.UUID, user_id: uuid.UUID) -> User | None:
        result = await self.session.execute(
            select(User).where(User.id == user_id, User.organisation_id == organisation_id)
        )
        return result.scalar_one_or_none()

    async def get_organisation(self, organisation_id: uuid.UUID) -> Organisation | None:
        return await self.session.get(Organisation, organisation_id)

    async def create_organisation(self, name: str) -> Organisation:
        org = Organisation(name=name)
        self.session.add(org)
        await self.session.flush()
        return org

    async def create_user(
        self, organisation_id: uuid.UUID, email: str, name: str, password_hash: str, role: str
    ) -> User:
        user = User(
            organisation_id=organisation_id,
            email=email.lower(),
            name=name,
            password_hash=password_hash,
            role=role,
        )
        self.session.add(user)
        await self.session.flush()
        return user
