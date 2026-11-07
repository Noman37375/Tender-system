"""Real LLMClient (PRD 9): budget check, retries, repair re-prompt, usage + cost accounting.

The client is provider-agnostic. The factory (app.llm.factory) wires it to a provider through
two callables, so tests can drive it without any network:
- `call_model(model, schema, system, user, temperature, max_output_tokens) -> ProviderResponse`
- `embed_texts(texts) -> list[list[float]]`

Logging (S-07): run_id, node, prompt_version, model, tokens, latency, cost — never prompt text.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel

from app.llm import retry
from app.llm.adapter import BudgetExceededError, CallUsage, ModelTier, T
from app.llm.costing import PriceTable, cost_for, load_price_table
from app.llm.structured import ProviderResponse, structured_call

log = structlog.get_logger(__name__)

EMBEDDING_DIM = 1536

CallModel = Callable[[str, type[BaseModel], str, str, float, int], Awaitable[ProviderResponse]]
EmbedTexts = Callable[[list[str]], Awaitable[list[list[float]]]]


class LLMConfigError(RuntimeError):
    """A model or provider needed for this call is not configured."""


class EmbeddingDimensionError(ValueError):
    """The embedding model returned vectors that are not 1536-dimensional."""


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


class LangChainLLMClient:
    def __init__(
        self,
        *,
        call_model: CallModel | None,
        embed_texts: EmbedTexts | None,
        model_fast: str,
        model_strong: str,
        embedding_model: str = "",
        usage: CallUsage | None = None,
        budget_usd: Decimal | None = None,
        spent_usd: Decimal = Decimal("0"),
        timeout_seconds: float = 120,
        price_table: PriceTable | None = None,
        retry_delays: tuple[float, ...] = retry.RETRY_DELAYS,
    ) -> None:
        self._call_model = call_model
        self._embed_texts = embed_texts
        self.models: dict[ModelTier, str] = {"fast": model_fast, "strong": model_strong}
        self.embedding_model = embedding_model
        self.usage = usage if usage is not None else CallUsage()
        self.budget_usd = budget_usd
        self.spent_usd = Decimal(spent_usd)
        self.timeout_seconds = timeout_seconds
        self.price_table = price_table if price_table is not None else load_price_table()
        self.retry_delays = retry_delays

    # ---------------------------------------------------------------- budget + accounting
    @property
    def total_spent_usd(self) -> Decimal:
        return self.spent_usd + self.usage.cost_usd

    def check_budget(self) -> None:
        """Raise before a call once the run's cost has passed its budget (PRD 7.5, S-10)."""
        if self.budget_usd is not None and self.total_spent_usd > self.budget_usd:
            raise BudgetExceededError(
                f"Run cost {self.total_spent_usd:.4f} USD exceeds budget {self.budget_usd} USD"
            )

    def _record(self, model: str, tokens_in: int, tokens_out: int, prompt_version: str) -> Decimal:
        cost = cost_for(model, tokens_in, tokens_out, self.price_table)
        self.usage.tokens_in += tokens_in
        self.usage.tokens_out += tokens_out
        self.usage.cost_usd += cost
        if model and model not in self.usage.models:
            self.usage.models.append(model)
        if prompt_version and prompt_version not in self.usage.prompt_versions:
            self.usage.prompt_versions.append(prompt_version)
        return cost

    # ---------------------------------------------------------------- structured
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
        model = self.models.get(model_tier, "")
        if not model:
            env = "LLM_MODEL_FAST" if model_tier == "fast" else "LLM_MODEL_STRONG"
            raise LLMConfigError(f"{env} is not set")
        if self._call_model is None:
            raise LLMConfigError("No chat provider configured")
        call_model = self._call_model
        fields: dict[str, Any] = {
            "run_id": run_id,
            "node": node,
            "prompt_version": prompt_version,
            "model": model,
        }

        async def invoke(sys_text: str, user_text: str) -> ProviderResponse:
            async def once() -> ProviderResponse:
                return await asyncio.wait_for(
                    call_model(model, schema, sys_text, user_text, temperature, max_output_tokens),
                    timeout=self.timeout_seconds + 5,
                )

            started = time.monotonic()
            response = await retry.with_retries(
                once,
                delays=self.retry_delays,
                before_attempt=self.check_budget,
                log_fields=fields,
            )
            used_model = response.model or model
            cost = self._record(used_model, response.tokens_in, response.tokens_out, prompt_version)
            log.info(
                "llm.call",
                **{**fields, "model": used_model},
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                latency_ms=int((time.monotonic() - started) * 1000),
                cost_usd=str(cost),
            )
            return response

        return await structured_call(invoke, schema, system=system, user=user, log_fields=fields)

    # ---------------------------------------------------------------- embeddings
    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._embed_texts is None or not self.embedding_model:
            raise LLMConfigError("EMBEDDING_MODEL is not set")
        embed_texts = self._embed_texts

        async def once() -> list[list[float]]:
            return await asyncio.wait_for(embed_texts(texts), timeout=self.timeout_seconds + 5)

        started = time.monotonic()
        vectors = await retry.with_retries(
            once,
            delays=self.retry_delays,
            before_attempt=self.check_budget,
            log_fields={"model": self.embedding_model, "node": "embed"},
        )
        if len(vectors) != len(texts):
            raise EmbeddingDimensionError(
                f"Embedding count {len(vectors)} does not match input count {len(texts)}"
            )
        for vec in vectors:
            if len(vec) != EMBEDDING_DIM:
                raise EmbeddingDimensionError(
                    f"Embedding model {self.embedding_model} returned {len(vec)} dims, "
                    f"expected {EMBEDDING_DIM} (chunks.embedding is vector({EMBEDDING_DIM}))"
                )
        tokens = sum(estimate_tokens(t) for t in texts)  # SDK does not report usage here
        cost = self._record(self.embedding_model, tokens, 0, "")
        log.info(
            "llm.embed",
            model=self.embedding_model,
            texts=len(texts),
            tokens_in_est=tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=str(cost),
        )
        return vectors
