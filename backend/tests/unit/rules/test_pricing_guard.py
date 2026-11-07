import pytest

from app.rules.pricing_guard import PRICING_PLACEHOLDER, find_leaks, scan, scan_form
from app.schemas.audit import FindingType
from app.schemas.forms import FormField, TenderForm


@pytest.mark.parametrize(
    "sentence",
    [
        "The total cost of the solution is PKR 12,500,000.",
        "Our hourly rate is Rs. 5,000 for senior engineers.",
        "Licences are priced at USD 20 per user.",
        "We quote $45,000 for the implementation.",
        "An annual support fee of AED 10,000 applies.",
        "Price: SAR 75,000 inclusive of taxes.",
        "Hosting is 1,200 USD per month.",
        "Training charges amount to PKR 2 million.",
    ],
)
def test_price_in_technical_section_is_replaced(sentence: str) -> None:
    md = f"## Approach\n\nWe follow agile delivery. {sentence} Testing happens weekly.\n"
    result = scan("technical_solution", md)
    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.type == FindingType.PRICING_LEAK
    assert f.severity == "BLOCKER"
    assert f.section_key == "technical_solution"
    assert PRICING_PLACEHOLDER in result.cleaned_md
    assert "We follow agile delivery." in result.cleaned_md
    assert "Testing happens weekly." in result.cleaned_md
    assert sentence not in result.cleaned_md


def test_amount_without_price_context_is_not_flagged() -> None:
    md = "The platform supports 5,000 users and PKR 1 transactions are logged."
    assert scan("technical_solution", md).findings == []
    assert scan("architecture", "Version 2.5 is used.").findings == []


def test_turnover_and_project_values_allowed_in_profile_and_experience() -> None:
    profile = "Our audited turnover was PKR 450 million in FY2024, at a cost-efficient margin."
    assert scan("company_profile", profile).findings == []
    exp = "- The project, valued at Rs. 120,000,000, cost PKR 120M and was delivered in 2023."
    assert scan("experience", exp).findings == []
    # a genuine price is still a leak, even in company_profile
    leak = "Our daily rate is USD 800."
    assert len(scan("company_profile", leak).findings) == 1
    # but turnover wording in a technical section with price context is a leak
    assert len(scan("methodology", "Turnover cost is PKR 5M.").findings) == 1


def test_list_items_and_tables_keep_structure() -> None:
    md = (
        "- Item one\n"
        "- Licence cost: PKR 900,000 per year\n"
        "| Component | Cost |\n"
        "|---|---|\n"
        "| Server | Rs 300,000 price |\n"
    )
    result = scan("scope_of_work", md)
    lines = result.cleaned_md.splitlines()
    assert lines[1] == f"- {PRICING_PLACEHOLDER}"
    assert lines[4] == f"| Server | {PRICING_PLACEHOLDER} |"
    assert len(result.findings) == 2


def test_rs_abbreviation_does_not_split_sentence() -> None:
    md = "The fee is Rs. 5,000 and the rate is Rs. 7,000 per day. Next sentence stays."
    result = scan("support", md)
    assert result.cleaned_md == f"{PRICING_PLACEHOLDER} Next sentence stays."
    assert len(result.findings) == 1


def test_idempotent_and_crlf() -> None:
    md = "Line one.\r\nThe cost is USD 5,000.\r\nLine three."
    once = scan("deployment", md)
    assert once.cleaned_md == f"Line one.\r\n{PRICING_PLACEHOLDER}\r\nLine three."
    assert scan("deployment", once.cleaned_md).findings == []


def test_find_leaks() -> None:
    assert find_leaks("timeline", "The cost is $10. Fine.") == ["The cost is $10."]


def test_scan_form_skips_financial_and_flags_technical() -> None:
    fields = [
        FormField(label="Bid price", value="PKR 9,000,000 total price", status="FILLED"),
        FormField(label="Name", value=None, status="NEEDS_INPUT"),
    ]
    tech = TenderForm(form_code="F-2", title="Tech", source_page=4, envelope="TECHNICAL", fields=fields)
    fin = TenderForm(form_code="F-9", title="Fin", source_page=9, envelope="FINANCIAL", fields=fields)
    findings = scan_form(tech)
    assert len(findings) == 1 and findings[0].type == FindingType.PRICING_LEAK
    assert scan_form(fin) == []
