"""Build the configured LLMClient from settings (PRD 9, D5, §17)."""

from decimal import Decimal

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.llm.adapter import CallUsage, LLMClient
from app.llm.client import LangChainLLMClient
from app.llm.providers import anthropic as anthropic_provider
from app.llm.providers import openai as openai_provider
from app.llm.providers.common import invoke_structured
from app.llm.structured import ProviderResponse


class ChatCache:
    """One LangChain chat model per (model, temperature, max tokens); SDK clients are shared."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[tuple[str, float, int], BaseChatModel] = {}

    def get(self, model: str, temperature: float, max_output_tokens: int) -> BaseChatModel:
        key = (model, temperature, max_output_tokens)
        if key not in self._cache:
            s = self.settings
            if s.LLM_PROVIDER == "anthropic":
                chat = anthropic_provider.build_chat_model(
                    model=model,
                    api_key=s.ANTHROPIC_API_KEY,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    timeout=s.LLM_TIMEOUT_SECONDS,
                )
            else:
                chat = openai_provider.build_chat_model(
                    model=model,
                    api_key=s.OPENAI_API_KEY,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    timeout=s.LLM_TIMEOUT_SECONDS,
                )
            self._cache[key] = chat
        return self._cache[key]

    async def call(
        self,
        model: str,
        schema: type[BaseModel],
        system: str,
        user: str,
        temperature: float,
        max_output_tokens: int,
    ) -> ProviderResponse:
        chat = self.get(model, temperature, max_output_tokens)
        return await invoke_structured(chat, schema, system, user, model)


def build_llm_client(
    usage: CallUsage | None = None,
    budget_usd: Decimal | None = None,
    spent_usd: Decimal = Decimal("0"),
) -> LLMClient:
    """Client for one node execution.

    usage: accumulator the node copies into agent_steps (a new one if None).
    budget_usd: run budget; None -> settings.RUN_BUDGET_USD (S-10: always enforced).
    spent_usd: what the run has already spent before this node.
    Missing model names / keys fail at call time with LLMConfigError, so building a client
    for embeddings only (ingestion) works without chat models configured.
    """
    s = get_settings()
    chats = ChatCache(s)
    embed_texts = None
    if s.EMBEDDING_MODEL:
        embeddings = openai_provider.build_embeddings(
            model=s.EMBEDDING_MODEL, api_key=s.OPENAI_API_KEY, timeout=s.LLM_TIMEOUT_SECONDS
        )
        embed_texts = embeddings.aembed_documents
    budget = budget_usd if budget_usd is not None else Decimal(str(s.RUN_BUDGET_USD))
    return LangChainLLMClient(
        call_model=chats.call,
        embed_texts=embed_texts,
        model_fast=s.LLM_MODEL_FAST,
        model_strong=s.LLM_MODEL_STRONG,
        embedding_model=s.EMBEDDING_MODEL,
        usage=usage,
        budget_usd=budget,
        spent_usd=Decimal(spent_usd),
        timeout_seconds=s.LLM_TIMEOUT_SECONDS,
    )
