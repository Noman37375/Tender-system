from datetime import date

import pytest

from app.rules.parsing import (
    fiscal_year_end,
    is_currency_unit,
    normalise_currency,
    parse_date,
    parse_number,
    subtract_years,
    years_between,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (5, 5.0),
        (2.5, 2.5),
        ("50,000,000", 50_000_000.0),
        ("PKR 50M", 50_000_000.0),
        ("1.2 billion", 1_200_000_000.0),
        ("3 crore", 30_000_000.0),
        ("12k", 12_000.0),
        ("n/a", None),
        (None, None),
        (True, None),
        ([1], None),
    ],
)
def test_parse_number(raw: object, expected: float | None) -> None:
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2023-06-30", date(2023, 6, 30)),
        ("2023-06-30T10:00:00Z", date(2023, 6, 30)),
        (date(2020, 1, 2), date(2020, 1, 2)),
        ("30/06/2023", date(2023, 6, 30)),
        ("30 June 2023", date(2023, 6, 30)),
        ("2023-02", date(2023, 2, 28)),
        ("2023-12", date(2023, 12, 31)),
        ("June 2023", date(2023, 6, 30)),
        ("2021", date(2021, 12, 31)),
        (2021, date(2021, 12, 31)),
        (99, None),
        ("", None),
        ("someday", None),
        ("2023-13", None),
        (None, None),
        (1.5, None),
    ],
)
def test_parse_date(raw: object, expected: date | None) -> None:
    assert parse_date(raw) == expected


def test_parse_date_datetime() -> None:
    from datetime import datetime

    assert parse_date(datetime(2022, 3, 4, 5, 6)) == date(2022, 3, 4)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2022-23", 2023),
        ("FY2022-2023", 2023),
        ("1999-00", 2000),
        ("FY2024", 2024),
        (2021, 2021),
        (2021.0, 2021),
        (date(2020, 6, 30), 2020),
        ("2023-06-30", 2023),
        ("2022-2025", None),
        ("unknown", None),
        (None, None),
        (5, None),
        ([], None),
    ],
)
def test_fiscal_year_end(raw: object, expected: int | None) -> None:
    assert fiscal_year_end(raw) == expected


def test_currency_helpers() -> None:
    assert normalise_currency("Rs.") == "PKR"
    assert normalise_currency("rs") == "PKR"
    assert normalise_currency("$") == "USD"
    assert normalise_currency("aed") == "AED"
    assert normalise_currency("CHF") == "CHF"
    assert normalise_currency("") is None
    assert normalise_currency("rupees!!") is None
    assert normalise_currency(None) is None
    assert is_currency_unit("PKR")
    assert not is_currency_unit("projects")
    assert not is_currency_unit(None)


def test_year_math() -> None:
    assert years_between(date(2016, 1, 1), date(2026, 1, 1)) == pytest.approx(10.0)
    assert years_between(date(2020, 2, 29), date(2021, 3, 1)) > 1.0
    assert subtract_years(date(2024, 2, 29), 3) == date(2021, 2, 28)
    assert subtract_years(date(2026, 6, 30), 5) == date(2021, 6, 30)
