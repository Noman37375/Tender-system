"""OpenAI chat + embeddings via langchain-openai. No retries here: app.llm.retry owns them."""

import re

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

EMBEDDING_DIM = 1536

# Reasoning models only accept the default temperature.
_NO_TEMPERATURE = re.compile(r"^(o\d|gpt-5)")


def supports_temperature(model: str) -> bool:
    return not _NO_TEMPERATURE.match(model)


def build_chat_model(
    *, model: str, api_key: str, temperature: float, max_output_tokens: int, timeout: float
) -> BaseChatModel:
    kwargs: dict[str, object] = {
        "model": model,
        "max_completion_tokens": max_output_tokens,
        "timeout": timeout,
        "max_retries": 0,
    }
    if api_key:
        kwargs["api_key"] = SecretStr(api_key)
    if supports_temperature(model):
        kwargs["temperature"] = temperature
    return ChatOpenAI(**kwargs)


def build_embeddings(*, model: str, api_key: str, timeout: float) -> OpenAIEmbeddings:
    kwargs: dict[str, object] = {
        "model": model,
        "timeout": timeout,
        "max_retries": 0,
        # Skip tiktoken length checks: they download encodings at runtime. Our inputs are
        # chunks (~800 tokens) and short descriptions, well under the model limit.
        "check_embedding_ctx_length": False,
    }
    if model.startswith("text-embedding-3"):
        kwargs["dimensions"] = EMBEDDING_DIM
    if api_key:
        kwargs["api_key"] = SecretStr(api_key)
    return OpenAIEmbeddings(**kwargs)
