from collections.abc import AsyncIterator

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import get_sessionmaker
from app.graph.executor import RunExecutor
from tests.graph.fakes import Scenario, install, make_executor


@pytest.fixture
def scenario(monkeypatch: pytest.MonkeyPatch) -> Scenario:
    sc = Scenario()
    install(monkeypatch, sc)
    return sc


@pytest.fixture
def sessionmaker() -> async_sessionmaker[AsyncSession]:
    return get_sessionmaker()


@pytest.fixture
async def executor(
    sessionmaker: async_sessionmaker[AsyncSession], scenario: Scenario
) -> AsyncIterator[RunExecutor]:
    ex = make_executor(sessionmaker, InMemorySaver())
    yield ex
    await ex.aclose()
