import uuid

import pytest

from app.security.auth import (
    InvalidTokenError,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    h = hash_password("s3cret-pass")
    assert h != "s3cret-pass"
    assert verify_password("s3cret-pass", h)
    assert not verify_password("other", h)


def test_token_roundtrip_carries_org() -> None:
    user, org = uuid.uuid4(), uuid.uuid4()
    claims = decode_token(create_token(user, org, "access"), "access")
    assert (claims.user_id, claims.organisation_id) == (user, org)


def test_wrong_token_type_rejected() -> None:
    token = create_token(uuid.uuid4(), uuid.uuid4(), "refresh")
    with pytest.raises(InvalidTokenError):
        decode_token(token, "access")


def test_tampered_token_rejected() -> None:
    token = create_token(uuid.uuid4(), uuid.uuid4(), "access")
    with pytest.raises(InvalidTokenError):
        decode_token(token[:-2] + "xx", "access")
