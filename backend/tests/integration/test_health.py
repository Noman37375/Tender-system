import pytest
from httpx import AsyncClient

from app.config import get_settings


async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}


async def test_readyz_reports_missing_llm_keys(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 503
    checks = resp.json()["checks"]
    assert checks["database"] == "ok"
    assert "OPENAI_API_KEY" in checks["llm_keys"]


async def test_readyz_ready_when_keys_present(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "OPENAI_API_KEY", "sk-test")
    resp = await client.get("/readyz")
    assert resp.status_code == 200 and resp.json()["status"] == "ready"


def test_anthropic_still_needs_embedding_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert settings.llm_keys_missing() == ["OPENAI_API_KEY"]
