"""Shared LangChain plumbing: force one tool call for the schema and read its arguments."""

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.llm.structured import ProviderResponse


def _text_of(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def _usage(message: AIMessage) -> tuple[int, int]:
    usage = message.usage_metadata
    if not usage:
        return 0, 0
    return int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)


def parse_tool_response(
    message: AIMessage, schema: type[BaseModel], default_model: str
) -> ProviderResponse:
    """Arguments of the schema's tool call; `args=None` plus an error if it is missing/bad."""
    tokens_in, tokens_out = _usage(message)
    meta = message.response_metadata or {}
    model = str(meta.get("model_name") or meta.get("model") or default_model)
    name = schema.__name__
    for call in message.tool_calls:
        if call.get("name") == name:
            args: dict[str, Any] = dict(call.get("args") or {})
            return ProviderResponse(
                args=args,
                raw_text=json.dumps(args, ensure_ascii=False, default=str),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
            )
    for bad in message.invalid_tool_calls:
        if bad.get("name") in (name, None):
            return ProviderResponse(
                args=None,
                raw_text=str(bad.get("args") or ""),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                model=model,
                error="The tool call arguments were not valid JSON (output may be truncated).",
            )
    return ProviderResponse(
        args=None,
        raw_text=_text_of(message),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        model=model,
        error=f"No call to the '{name}' tool was returned; answer only by calling it.",
    )


async def invoke_structured(
    chat: BaseChatModel, schema: type[BaseModel], system: str, user: str, model_name: str
) -> ProviderResponse:
    """Native structured output via a forced tool call (works for OpenAI and Anthropic).

    Not OpenAI strict mode: several schemas carry free-form dicts (evidence attributes,
    architecture components) that strict JSON schema cannot express. Pydantic validates after.
    """
    bound = chat.bind_tools([schema], tool_choice=schema.__name__, parallel_tool_calls=False)
    message = await bound.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
    if not isinstance(message, AIMessage):  # pragma: no cover - defensive
        raise TypeError(f"Unexpected chat response type {type(message).__name__}")
    return parse_tool_response(message, schema, model_name)
