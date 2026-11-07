"""Provider-agnostic LLM interface (PRD §9). All LLM calls go through an LLMClient.

CONTRACT (fixed): the signature of `structured` and `embed`. Providers live in app/llm/providers/.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
ModelTier = Literal["fast", "strong"]


@dataclass
class CallUsage:
    """Accumulated usage for one node execution; nodes copy it into agent_steps."""

    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    models: list[str] = field(default_factory=list)
    prompt_versions: list[str] = field(default_factory=list)


class BudgetExceededError(RuntimeError):
    """Run cost passed budget_usd; raised before the next LLM call (PRD 7.5)."""


class LLMClient(Protocol):
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
        """Return an instance of `schema`. Validates with Pydantic; on failure re-prompts once
        with the validation error, then raises. Retries transient errors (3x, backoff+jitter)."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """1536-dim vectors, one per text."""
        ...
