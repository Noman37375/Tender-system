import uuid

from httpx import AsyncClient

from app.security.auth import create_token
from tests.conftest import register


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_register_creates_org_and_admin(client: AsyncClient) -> None:
    body = await register(client, "Owner@Example.com")
    assert body["user"]["email"] == "owner@example.com"  # stored lower-case
    assert body["user"]["role"] == "admin"
    me = await client.get("/api/v1/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["organisation"]["name"] == "Acme Networks"
    assert me.json()["organisation"]["jurisdiction"] == "PK"


async def test_register_duplicate_email_rejected(client: AsyncClient) -> None:
    await register(client, "dup@example.com")
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "org_name": "Other",
            "name": "X",
            "email": "DUP@example.com",
            "password": "another-pass-1",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "EMAIL_TAKEN"


async def test_register_validates_input(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"org_name": "A", "name": "B", "email": "not-an-email", "password": "short"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_login_success_and_failure(client: AsyncClient) -> None:
    await register(client, "login@example.com")
    ok = await client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "correct-horse-1"}
    )
    assert ok.status_code == 200 and ok.json()["access_token"]

    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "login@example.com", "password": "wrong-password"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "correct-horse-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # no hint whether the email exists


async def test_refresh_issues_new_access_token(client: AsyncClient) -> None:
    body = await register(client, "refresh@example.com")
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert resp.status_code == 200
    assert (
        await client.get("/api/v1/me", headers=bearer(resp.json()["access_token"]))
    ).status_code == 200


async def test_token_types_are_not_interchangeable(client: AsyncClient) -> None:
    body = await register(client, "types@example.com")
    as_access = await client.get("/api/v1/me", headers=bearer(body["refresh_token"]))
    as_refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": body["access_token"]}
    )
    assert as_access.status_code == 401
    assert as_refresh.status_code == 401


async def test_me_requires_valid_token(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/me")).status_code == 401
    assert (await client.get("/api/v1/me", headers=bearer("garbage"))).status_code == 401


async def test_token_with_wrong_organisation_is_rejected(client: AsyncClient) -> None:
    """A user id paired with another org's id must not authenticate (S-01)."""
    a = await register(client, "a@example.com", org="Org A")
    b = await register(client, "b@example.com", org="Org B")
    forged = create_token(
        uuid.UUID(a["user"]["id"]), uuid.UUID(b["user"]["organisation_id"]), "access"
    )
    assert (await client.get("/api/v1/me", headers=bearer(forged))).status_code == 401
