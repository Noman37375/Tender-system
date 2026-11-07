"""Anthropic chat via langchain-anthropic. Anthropic has no embeddings API (PRD D5)."""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import SecretStr


def build_chat_model(
    *, model: str, api_key: str, temperature: float, max_output_tokens: int, timeout: float
) -> BaseChatModel:
    kwargs: dict[str, object] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_output_tokens,
        "timeout": timeout,
        "max_retries": 0,
    }
    if api_key:
        kwargs["api_key"] = SecretStr(api_key)
    return ChatAnthropic(**kwargs)
