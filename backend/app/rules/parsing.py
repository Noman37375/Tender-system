"""Tolerant parsers for LLM-extracted evidence attributes (numbers, dates, currencies).

Evidence attributes come from LLM extraction, so values may be strings ("PKR 50,000,000",
"50M", "2023-06-30", "FY2022-23"), numbers, or missing. Every parser returns None when it
cannot read the value; callers treat None as "not evidenced" (conservative).
"""

import re
from datetime import date, datetime, timedelta
from typing import Any

_MULTIPLIERS: dict[str, float] = {
    "k": 1e3,
    "thousand": 1e3,
    "lakh": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "lakhs": 1e5,
    "m": 1e6,
    "mn": 1e6,
    "mio": 1e6,
    "million": 1e6,
    "millions": 1e6,
    "cr": 1e7,
    "crore": 1e7,
    "crores": 1e7,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "billions": 1e9,
}

_NUMBER_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*([a-zA-Z]+)?")

_CURRENCY_ALIASES: dict[str, str] = {
    "PKR": "PKR",
    "RS": "PKR",
    "RS.": "PKR",
    "RUPEE": "PKR",
    "RUPEES": "PKR",
    "USD": "USD",
    "US$": "USD",
    "$": "USD",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "AED": "AED",
    "DIRHAM": "AED",
    "DIRHAMS": "AED",
    "SAR": "SAR",
    "RIYAL": "SAR",
    "RIYALS": "SAR",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
}


def parse_number(value: Any) -> float | None:
    """Read a number from int/float/str such as "50,000,000", "PKR 50M", "1.2 billion"."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMBER_RE.search(value)
    if match is None:
        return None
    try:
        number = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = (match.group(2) or "").lower()
    return number * _MULTIPLIERS.get(suffix, 1.0)


def parse_date(value: Any) -> date | None:
    """Read a date from date/datetime/ISO strings; "2021" -> 31 Dec, "2021-06" -> 30 Jun-ish.

    Partial dates resolve to the END of the period, so a project ending "2021" is not
    counted as inside a window that starts in mid-2021 unless it really could be.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int):
        return date(value, 12, 31) if 1900 <= value <= 2200 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    ym = re.fullmatch(r"(\d{4})[-/](\d{1,2})", text)
    if ym:
        year, month = int(ym.group(1)), int(ym.group(2))
        if 1 <= month <= 12:
            return _month_end(year, month)
    for fmt in ("%B %Y", "%b %Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
            return _month_end(parsed.year, parsed.month)
        except ValueError:
            continue
    year_only = re.fullmatch(r"(\d{4})", text)
    if year_only:
        return date(int(year_only.group(1)), 12, 31)
    return None


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def fiscal_year_end(value: Any) -> int | None:
    """Ending calendar year of a fiscal year: "2022-23" -> 2023, "FY2024" -> 2024, 2021 -> 2021."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1900 <= value <= 2200 else None
    if isinstance(value, float):
        return int(value) if 1900 <= value <= 2200 else None
    if isinstance(value, date):
        return value.year
    if not isinstance(value, str):
        return None
    text = value.strip()
    pair = re.search(r"(\d{4})\s*[-/–]\s*(\d{2,4})\b", text)
    if pair:
        start, end_raw = int(pair.group(1)), pair.group(2)
        end = int(end_raw) if len(end_raw) == 4 else (start // 100) * 100 + int(end_raw)
        if end < start:  # "1999-00"
            end += 100
        if 1 <= end - start <= 1:
            return end
        parsed = parse_date(text)
        return parsed.year if parsed else None
    years = re.findall(r"(?<!\d)(\d{4})(?!\d)", text)
    if years:
        return int(years[-1])
    return None


def normalise_currency(value: Any) -> str | None:
    """Map "Rs."/"PKR"/"$"/"US$" etc. to an ISO-like code; None if absent/unknown."""
    if not isinstance(value, str):
        return None
    key = value.strip().upper()
    if not key:
        return None
    if key in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[key]
    stripped = key.rstrip(".")
    if stripped in _CURRENCY_ALIASES:
        return _CURRENCY_ALIASES[stripped]
    return key if re.fullmatch(r"[A-Z]{3}", key) else None


KNOWN_CURRENCIES = frozenset(_CURRENCY_ALIASES.values())


def is_currency_unit(unit: str | None) -> bool:
    code = normalise_currency(unit)
    return code is not None and code in KNOWN_CURRENCIES


def years_between(start: date, end: date) -> float:
    """Whole + fractional years from start to end (negative if end < start)."""
    full = end.year - start.year - ((end.month, end.day) < (start.month, start.day))
    anchor_year = start.year + full
    try:
        anchor = start.replace(year=anchor_year)
    except ValueError:  # 29 Feb
        anchor = start.replace(year=anchor_year, day=28)
    return full + (end - anchor).days / 365.25


def subtract_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 Feb
        return day.replace(year=day.year - years, day=28)
