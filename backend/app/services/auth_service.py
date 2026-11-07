from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.errors import ApiError
from app.repositories.users import UserRepository
from app.security.auth import (
    InvalidTokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

# Compared against when the email is unknown, so login takes the same time either way.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-password")


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    user: User


def _issue(user: User) -> IssuedTokens:
    return IssuedTokens(
        access_token=create_token(user.id, user.organisation_id, "access"),
        refresh_token=create_token(user.id, user.organisation_id, "refresh"),
        user=user,
    )


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register(self, org_name: str, name: str, email: str, password: str) -> IssuedTokens:
        """Create a new organisation with its first user as admin."""
        if await self.users.get_by_email(email):
            raise ApiError(409, "EMAIL_TAKEN", "An account with this email already exists")
        try:
            org = await self.users.create_organisation(org_name)
            user = await self.users.create_user(
                org.id, email, name, hash_password(password), role="admin"
            )
            await self.session.commit()
        except IntegrityError as exc:  # concurrent registration with the same email
            await self.session.rollback()
            raise ApiError(409, "EMAIL_TAKEN", "An account with this email already exists") from exc
        return _issue(user)

    async def login(self, email: str, password: str) -> IssuedTokens:
        user = await self.users.get_by_email(email)
        valid = verify_password(password, user.password_hash if user else _DUMMY_HASH)
        if user is None or not valid:
            raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect")
        return _issue(user)

    async def refresh(self, refresh_token: str) -> str:
        try:
            claims = decode_token(refresh_token, "refresh")
        except InvalidTokenError as exc:
            raise ApiError(401, "INVALID_TOKEN", str(exc)) from exc
        user = await self.users.get(claims.organisation_id, claims.user_id)
        if user is None:
            raise ApiError(401, "INVALID_TOKEN", "User no longer exists")
        return create_token(user.id, user.organisation_id, "access")
