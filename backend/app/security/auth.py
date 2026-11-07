"""Password hashing (bcrypt) and JWT access/refresh tokens (PRD S-02)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import bcrypt
import jwt

from app.config import get_settings

TokenType = Literal["access", "refresh"]
ALGORITHM = "HS256"


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    organisation_id: uuid.UUID
    token_type: TokenType


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user_id: uuid.UUID, organisation_id: uuid.UUID, token_type: TokenType) -> str:
    settings = get_settings()
    lifetime = (
        timedelta(minutes=settings.JWT_ACCESS_MINUTES)
        if token_type == "access"
        else timedelta(days=settings.JWT_REFRESH_DAYS)
    )
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(organisation_id),
        "type": token_type,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    try:
        payload = jwt.decode(token, get_settings().JWT_SECRET, algorithms=[ALGORITHM])
        claims = TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            organisation_id=uuid.UUID(payload["org"]),
            token_type=payload["type"],
        )
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise InvalidTokenError("Invalid or expired token") from exc
    if claims.token_type != expected_type:
        raise InvalidTokenError(f"Expected a {expected_type} token")
    return claims
