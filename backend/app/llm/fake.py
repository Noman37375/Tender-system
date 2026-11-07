"""FakeLLMClient for tests: returns queued fixture responses per node, records every call."""

import hashlib
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.llm.adapter import ModelTier, T

Responder = Callable[[str, str, type[BaseModel]], BaseModel | dict[str, Any]]


@dataclass
class RecordedCall:
    node: str
    schema: str
    system: str
    user: str
    model_tier: ModelTier


class FakeLLMClient:
    """Queue responses with `add(node, response)` or set a function with `on(node, fn)`.

    A response may be a model instance or a dict (validated against the requested schema).
    `fn(system, user, schema)` lets a test build an answer from the prompt.
    """

    def __init__(self) -> None:
        self._queues: dict[str, deque[BaseModel | dict[str, Any]]] = defaultdict(deque)
        self._responders: dict[str, Responder] = {}
        self.calls: list[RecordedCall] = []

    def add(self, node: str, *responses: BaseModel | dict[str, Any]) -> "FakeLLMClient":
        self._queues[node].extend(responses)
        return self

    def on(self, node: str, fn: Responder) -> "FakeLLMClient":
        self._responders[node] = fn
        return self

    async def structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        model_tier: ModelTier,
        run_id: str,
        node: str,
        prompt_version: str = "",
        temperature: float = 0.1,
        max_output_tokens: int = 8000,
    ) -> T:
        self.calls.append(RecordedCall(node, schema.__name__, system, user, model_tier))
        if self._queues[node]:
            raw = self._queues[node].popleft()
        elif node in self._responders:
            raw = self._responders[node](system, user, schema)
        else:
            raise AssertionError(f"FakeLLMClient: no response queued for node '{node}'")
        return schema.model_validate(raw.model_dump() if isinstance(raw, BaseModel) else raw)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Deterministic pseudo-embeddings: same text, same vector."""
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode()).digest()
            out.append([digest[i % 32] / 255.0 for i in range(1536)])
        return out

    def calls_for(self, node: str) -> list[RecordedCall]:
        return [c for c in self.calls if c.node == node]
