from typing import Any

import pytest

from app.agents import company_extractor as ce
from app.llm.fake import FakeLLMClient
from app.schemas.evidence import EvidenceCategory, VerificationStatus
from tests.unit.agents.builders import page

DOC = "doc-company"
TEXT = (
    "ISO 9001:2015 certificate issued by SGS, valid until 12/03/2027. "
    "Completed HRMIS for the Punjab IT Board worth PKR 85,000,000 in March 2023. "
    "NTN registered with FBR."
)


def item(
    category: str, description: str, quote: str, status: str = "DOCUMENTED", **attrs: Any
) -> dict[str, Any]:
    return {
        "evidence_code": "EV-XYZ-999",
        "category": category,
        "description": description,
        "attributes": attrs,
        "source": {"document_id": DOC, "page": 1, "quote": quote},
        "verification_status": status,
    }


def answer() -> dict[str, Any]:
    return {
        "company_name": "Acme",
        "items": [
            item(
                "CERTIFICATION",
                "ISO 9001:2015",
                "ISO 9001:2015 certificate issued by SGS",
                name="ISO 9001:2015",
                issuer="SGS",
                expiry_date="12/03/2027",
            ),
            item(
                "PROJECT",
                "HRMIS for Punjab IT Board",
                "Completed HRMIS for the Punjab IT Board worth PKR 85,000,000",
                client="Punjab IT Board",
                value="PKR 85,000,000",
                end_date="March 2023",
                technologies="Java, Oracle",
            ),
            item(
                "TAX_REGISTRATION",
                "Registered with FBR",
                "NTN registered with FBR.",
                authority="FBR",
                ntn="1234567-8",
            ),
            item("CAPABILITY", "Quantum computing", "We build quantum computers.", "DOCUMENTED"),
        ],
        "extraction_warnings": [],
    }


async def run(kind: str) -> Any:
    llm = FakeLLMClient().add("company_extract", answer())
    result = await ce.extract_company_document(llm, kind, [page(1, TEXT, doc=DOC)], "r1")
    return llm, result


async def test_company_profile_claims_are_self_declared() -> None:
    llm, result = await run("COMPANY_PROFILE")
    call = llm.calls_for("company_extract")[0]
    assert call.schema == "CompanyEvidence" and "kind COMPANY_PROFILE" in call.user
    assert all(i.evidence_code == "TBD" for i in result.items)
    assert {i.verification_status for i in result.items} == {VerificationStatus.SELF_DECLARED}


async def test_certificate_document_proves_only_its_category() -> None:
    _, result = await run("CERTIFICATION")
    status = {i.category: i.verification_status for i in result.items}
    assert status[EvidenceCategory.CERTIFICATION] == VerificationStatus.DOCUMENTED
    assert status[EvidenceCategory.TAX_REGISTRATION] == VerificationStatus.DOCUMENTED
    assert status[EvidenceCategory.PROJECT] == VerificationStatus.SELF_DECLARED


async def test_completion_letter_documents_project_and_attributes_are_normalised() -> None:
    _, result = await run("PROJECT_CREDENTIAL")
    project = next(i for i in result.items if i.category == EvidenceCategory.PROJECT)
    assert project.verification_status == VerificationStatus.DOCUMENTED
    assert project.attributes["value"] == 85_000_000
    assert project.attributes["currency"] == "PKR"
    assert project.attributes["end_date"] == "2023-03-01"
    assert project.attributes["technologies"] == ["Java", "Oracle"]
    assert project.attributes["start_date"] is None  # missing keys filled with None

    cert = next(i for i in result.items if i.category == EvidenceCategory.CERTIFICATION)
    assert cert.attributes["expiry_date"] == "2027-03-12"

    tax = next(i for i in result.items if i.category == EvidenceCategory.TAX_REGISTRATION)
    assert "ntn" not in tax.attributes  # registration numbers never kept
    assert tax.attributes["number_present"] is True


async def test_unverifiable_quote_keeps_item_with_warning_and_no_documented_status() -> None:
    _, result = await run("CERTIFICATION")
    capability = next(i for i in result.items if i.category == EvidenceCategory.CAPABILITY)
    assert capability.verification_status == VerificationStatus.SELF_DECLARED
    assert any("could not be verified" in w for w in result.extraction_warnings)
    assert len(result.items) == 4  # never dropped


def test_expired_from_llm_is_never_stored() -> None:
    raw = ce.CompanyEvidence.model_validate(
        {"items": [item("CERTIFICATION", "ISO", "ISO 9001:2015 certificate", "EXPIRED")]}
    )
    out = ce.postprocess(raw, "CERTIFICATION", [page(1, TEXT, doc=DOC)])
    assert out.items[0].verification_status == VerificationStatus.DOCUMENTED


def test_unaudited_financial_statement_is_self_declared() -> None:
    raw = ce.CompanyEvidence.model_validate(
        {
            "items": [
                item("FINANCIAL", "Turnover FY2023", "ISO 9001:2015", audited="no",
                     metric="annual_turnover", value="50M")
            ]
        }
    )
    out = ce.postprocess(raw, "FINANCIAL_STATEMENT", [page(1, TEXT, doc=DOC)])
    assert out.items[0].verification_status == VerificationStatus.SELF_DECLARED
    assert out.items[0].attributes["value"] == 50_000_000


@pytest.mark.parametrize(
    ("raw", "iso"),
    [
        ("2023-06-30", "2023-06-30"),
        ("2023-06", "2023-06-01"),
        ("30/06/2023", "2023-06-30"),
        ("June 2023", "2023-06-01"),
        ("30 June 2023", "2023-06-30"),
        ("June 30, 2023", "2023-06-30"),
        ("2023", "2023-01-01"),
        ("sometime", None),
        (None, None),
    ],
)
def test_to_iso_date(raw: str | None, iso: str | None) -> None:
    assert ce.to_iso_date(raw) == iso


async def test_empty_document_makes_no_llm_call() -> None:
    llm = FakeLLMClient()
    result = await ce.extract_company_document(llm, "CV", [], "r1")
    assert result.items == [] and llm.calls == []
