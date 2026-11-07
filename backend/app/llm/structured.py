"""Schema-validated structured calls with ONE repair re-prompt (PRD 7.5, MASTER_PROMPT §5).

Provider-agnostic: a provider supplies `invoke(system, user) -> ProviderResponse`, where the
response carries the tool-call arguments (native structured output). This module validates
them with Pydantic; on failure it re-prompts once with the validation errors appended, and
raises StructuredOutputError if the second answer is still invalid.

Validation errors are reported without input values (`include_input=False`) so exception
messages and logs never echo document text (S-07).
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, ValidationError

log = structlog.get_logger(__name__)


MAX_PREVIOUS_OUTPUT_CHARS = 20_000

REPAIR_TEMPLATE = """{user}

---
YOUR PREVIOUS OUTPUT FAILED SCHEMA VALIDATION.
Errors:
{errors}

Previous output (for reference, may be truncated):
{previous}

Return a corrected, complete output that conforms exactly to the schema. Fix every error listed.
Do not add facts that are not in the inputs above."""


class StructuredOutputError(RuntimeError):
    """The model's output failed schema validation twice (after one repair re-prompt)."""


@dataclass
class ProviderResponse:
    args: dict[str, Any] | None  # parsed tool-call arguments; None if no (valid) tool call
    raw_text: str  # text content or raw argument string, for the repair prompt
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""
    error: str | None = None  # provider-level parse problem (e.g. no tool call, bad JSON)


Invoke = Callable[[str, str], Awaitable[ProviderResponse]]


def format_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        lines.append(f"- {loc}: {err.get('msg', 'invalid')}")
    return "\n".join(lines[:50])


def validate[T: BaseModel](
    schema: type[T], response: ProviderResponse
) -> tuple[T | None, str | None]:
    """(instance, None) on success, (None, error text) on failure."""
    if response.args is None:
        return None, response.error or "No structured output (tool call) was returned."
    try:
        return schema.model_validate(response.args), None
    except ValidationError as exc:
        return None, format_validation_error(exc)


def _previous_output(response: ProviderResponse) -> str:
    if response.args is not None:
        text = json.dumps(response.args, ensure_ascii=False, default=str)
    else:
        text = response.raw_text or "<empty>"
    if len(text) > MAX_PREVIOUS_OUTPUT_CHARS:
        text = text[:MAX_PREVIOUS_OUTPUT_CHARS] + " …[truncated]"
    return text


def build_repair_user(user: str, errors: str, response: ProviderResponse) -> str:
    return REPAIR_TEMPLATE.format(user=user, errors=errors, previous=_previous_output(response))


async def structured_call[T: BaseModel](
    invoke: Invoke,
    schema: type[T],
    *,
    system: str,
    user: str,
    log_fields: dict[str, Any] | None = None,
) -> T:
    """Call, validate, re-prompt once with the errors, validate again, else raise."""
    fields = log_fields or {}
    response = await invoke(system, user)
    result, errors = validate(schema, response)
    if result is not None:
        return result
    assert errors is not None
    log.warning("llm.validation_failed", schema=schema.__name__, repair=True, **fields)
    response = await invoke(system, build_repair_user(user, errors, response))
    result, errors = validate(schema, response)
    if result is not None:
        return result
    log.error("llm.validation_failed", schema=schema.__name__, repair=False, **fields)
    raise StructuredOutputError(
        f"{schema.__name__}: output invalid after one repair re-prompt:\n{errors}"
    )
