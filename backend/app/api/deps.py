from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_session
from app.errors import ApiError
from app.repositories.users import UserRepository
from app.security.auth import InvalidTokenError, decode_token

SessionDep = Annotated[AsyncSession, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise ApiError(401, "NOT_AUTHENTICATED", "Missing bearer token")
    try:
        claims = decode_token(credentials.credentials, "access")
    except InvalidTokenError as exc:
        raise ApiError(401, "INVALID_TOKEN", str(exc)) from exc
    user = await UserRepository(session).get(claims.organisation_id, claims.user_id)
    if user is None:
        raise ApiError(401, "INVALID_TOKEN", "User no longer exists")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
