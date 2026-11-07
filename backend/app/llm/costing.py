"""Per-model token prices (PRD 9: every call logs cost). Prices are USD per 1M tokens.

The defaults below are list prices at the time of writing and are only a starting point:
override or extend them with the env var LLM_PRICES_JSON, e.g.
    LLM_PRICES_JSON='{"gpt-4o": [2.5, 10], "my-private-model": [0, 0]}'
A model is matched exactly first, then by the longest table key that prefixes it (so dated
snapshots such as "gpt-4o-2024-08-06" use the "gpt-4o" price). Unknown model -> cost 0 and a
warning (logged once per model), so a missing price never blocks a run but is visible.
"""

import json
import os
from decimal import Decimal

import structlog

log = structlog.get_logger(__name__)

PriceTable = dict[str, tuple[Decimal, Decimal]]  # model -> (input per 1M, output per 1M)

_ONE_MILLION = Decimal(1_000_000)


def _p(inp: str, out: str) -> tuple[Decimal, Decimal]:
    return Decimal(inp), Decimal(out)


DEFAULT_PRICES: PriceTable = {
    # OpenAI chat
    "gpt-4o": _p("2.50", "10.00"),
    "gpt-4o-mini": _p("0.15", "0.60"),
    "gpt-4.1": _p("2.00", "8.00"),
    "gpt-4.1-mini": _p("0.40", "1.60"),
    "gpt-4.1-nano": _p("0.10", "0.40"),
    "gpt-5": _p("1.25", "10.00"),
    "gpt-5-mini": _p("0.25", "2.00"),
    "gpt-5-nano": _p("0.05", "0.40"),
    "o3": _p("2.00", "8.00"),
    "o4-mini": _p("1.10", "4.40"),
    # Anthropic chat
    "claude-opus-4": _p("15.00", "75.00"),
    "claude-opus-4-5": _p("5.00", "25.00"),
    "claude-sonnet-4": _p("3.00", "15.00"),
    "claude-haiku-4-5": _p("1.00", "5.00"),
    "claude-3-5-haiku": _p("0.80", "4.00"),
    # OpenAI embeddings (input only)
    "text-embedding-3-small": _p("0.02", "0"),
    "text-embedding-3-large": _p("0.13", "0"),
    "text-embedding-ada-002": _p("0.10", "0"),
}

_warned: set[str] = set()


def load_price_table() -> PriceTable:
    """DEFAULT_PRICES overlaid with LLM_PRICES_JSON (bad JSON is logged and ignored)."""
    table = dict(DEFAULT_PRICES)
    raw = os.environ.get("LLM_PRICES_JSON", "").strip()
    if not raw:
        return table
    try:
        data = json.loads(raw)
        for model, pair in data.items():
            table[str(model)] = (Decimal(str(pair[0])), Decimal(str(pair[1])))
    except (ValueError, TypeError, IndexError, KeyError, AttributeError):
        log.warning("llm.prices.invalid_json", env="LLM_PRICES_JSON")
    return table


def price_for(model: str, table: PriceTable | None = None) -> tuple[Decimal, Decimal] | None:
    table = table if table is not None else load_price_table()
    if model in table:
        return table[model]
    matches = [key for key in table if model.startswith(key)]
    if not matches:
        return None
    return table[max(matches, key=len)]


def cost_for(
    model: str, tokens_in: int, tokens_out: int, table: PriceTable | None = None
) -> Decimal:
    """USD cost of one call. Unknown model -> Decimal(0) with a one-time warning."""
    price = price_for(model, table)
    if price is None:
        if model not in _warned:
            _warned.add(model)
            log.warning("llm.prices.unknown_model", model=model)
        return Decimal("0")
    inp, out = price
    return (Decimal(tokens_in) * inp + Decimal(tokens_out) * out) / _ONE_MILLION
