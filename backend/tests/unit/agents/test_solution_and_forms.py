from typing import Any

from app.agents import form_detector as fd
from app.agents import solution_designer as sd
from app.llm.fake import FakeLLMClient
from app.schemas.evidence import EvidenceCategory as EC
from app.schemas.tender import ReqCategory as RC
from tests.unit.agents.builders import ev, page, req


def design(trace: dict[str, str], gaps: list[str] | None = None) -> dict[str, Any]:
    return {
        "approach_summary": "Agile delivery",
        "architecture_description": "Three tiers",
        "architecture_components": [{"name": "API", "maps_to_req_codes": ["TEC-001"]}],
        "requirement_traceability": trace,
        "phases": [{"name": "P1", "objective": "o", "activities": [], "deliverables": []}],
        "testing_strategy": "t",
        "deployment_strategy": "d",
        "support_model": "s",
        "assumptions": [],
        "risks": [],
        "capability_gaps": gaps or [],
    }


REQS = [
    req("TEC-001", "Single sign-on"),
    req("TEC-002", "Mobile app"),
    req("TEC-003", "Optional dashboard", mandatory=False),
    req("ELG-001", "Registered company", RC.ELIGIBILITY),
]
EVIDENCE = [
    ev("EV-CAP-001", EC.CAPABILITY, "SSO integration"),
    ev("EV-FIN-001", EC.FINANCIAL, "Turnover"),
]


async def test_solution_complete_traceability_single_call_and_filtered_inputs() -> None:
    llm = FakeLLMClient().add(
        "solution_design", design({"TEC-001": "Keycloak", "TEC-002": "Flutter", "ZZZ-1": "x"})
    )
    out = await sd.design_solution(llm, REQS, EVIDENCE, "HR system", run_id="r1")
    assert len(llm.calls) == 1
    user = llm.calls[0].user
    assert "TEC-001" in user and "ELG-001" not in user  # only TECHNICAL/DELIVERABLE/EVALUATION
    assert "EV-CAP-001" in user and "EV-FIN-001" not in user
    assert "ZZZ-1" not in out.requirement_traceability
    assert out.capability_gaps == []


async def test_solution_traceability_reprompt_then_capability_gap() -> None:
    llm = FakeLLMClient().add(
        "solution_design",
        design({"TEC-001": "Keycloak"}),  # TEC-002 missing
        design({"TEC-001": "Keycloak"}, gaps=["No mobile evidence"]),  # still missing
    )
    out = await sd.design_solution(llm, REQS, EVIDENCE, "HR system", run_id="r1")
    assert len(llm.calls) == 2
    assert "TEC-002" in llm.calls[1].user and "TRACEABILITY CHECK FAILED" in llm.calls[1].user
    assert out.capability_gaps[0] == "No mobile evidence"
    assert any(g.startswith("TEC-002:") for g in out.capability_gaps)
    assert not any(g.startswith("TEC-003:") for g in out.capability_gaps)  # optional req


async def test_solution_reprompt_fixes_traceability() -> None:
    llm = FakeLLMClient().add(
        "solution_design",
        design({"TEC-001": "Keycloak"}),
        design({"TEC-001": "Keycloak", "TEC-002": "Flutter"}),
    )
    out = await sd.design_solution(llm, REQS, EVIDENCE, "HR system", run_id="r1")
    assert out.capability_gaps == [] and "TEC-002" in out.requirement_traceability


# ------------------------------------------------------------------ forms
FORM_PAGES = [
    page(1, "Section 1. Instructions to bidders."),
    page(2, "Form TECH-1: Bidder Information\nName of bidder ...\nSignature of authorised person"),
    page(3, "continued fields"),
    page(7, "Schedule F: Price Schedule\nItem | Rate | Amount"),
]


def detected() -> dict[str, Any]:
    return {
        "forms": [
            {
                "form_code": "TECH-1",
                "title": "Bidder Information",
                "source_page": 2,
                "envelope": "TECHNICAL",
                "fields": [
                    {"label": "Name of bidder", "status": "NEEDS_INPUT"},
                    {"label": "Year of registration", "status": "NEEDS_INPUT"},
                    {"label": "Signature of authorised person", "status": "NEEDS_INPUT"},
                    {"label": "Date", "status": "NEEDS_INPUT"},
                ],
            },
            {
                "form_code": "Schedule F",
                "title": "Price Schedule",
                "source_page": 7,
                "envelope": "TECHNICAL",  # mislabelled by the model; title says financial
                "fields": [{"label": "Total bid amount", "status": "NEEDS_INPUT"}],
            },
        ]
    }


def filled() -> dict[str, Any]:
    return {
        "forms": [
            {
                "form_code": "TECH-1",
                "title": "Bidder Information",
                "source_page": 2,
                "envelope": "TECHNICAL",
                "fields": [
                    {"label": "Name of bidder", "value": "Acme", "evidence_codes": ["EV-REG-001"],
                     "status": "FILLED"},
                    {"label": "Year of registration", "value": "2010",
                     "evidence_codes": ["EV-FAKE-9"], "status": "FILLED"},
                    {"label": "Signature of authorised person", "value": "J. Smith",
                     "evidence_codes": ["EV-REG-001"], "status": "FILLED"},
                    {"label": "Date", "value": "2026-01-01", "evidence_codes": ["EV-REG-001"],
                     "status": "FILLED"},
                ],
            },
            {
                "form_code": "Schedule F",
                "title": "Price Schedule",
                "source_page": 7,
                "envelope": "FINANCIAL",
                "fields": [{"label": "Total bid amount", "value": "PKR 10M",
                            "evidence_codes": ["EV-REG-001"], "status": "FILLED"}],
            },
        ]
    }


async def test_forms_financial_not_filled_and_sensitive_fields_need_input() -> None:
    llm = FakeLLMClient().add("form_detection", detected(), filled())
    evidence = [ev("EV-REG-001", EC.COMPANY_REGISTRATION, "Acme registered with SECP")]
    forms = await fd.detect_forms(llm, FORM_PAGES, evidence, run_id="r1")
    assert len(llm.calls) == 2
    detect_user = llm.calls[0].user
    assert 'page="2"' in detect_user and 'page="3"' in detect_user and 'page="1"' not in detect_user
    assert "PASS 2" in llm.calls[1].user and "Schedule F" not in llm.calls[1].user

    tech, price = forms
    assert price.envelope == "FINANCIAL"
    assert all(f.value is None and f.status == "NEEDS_INPUT" for f in price.fields)
    fields = {f.label: f for f in tech.fields}
    assert fields["Name of bidder"].status == "FILLED"
    assert fields["Name of bidder"].evidence_codes == ["EV-REG-001"]
    assert fields["Year of registration"].status == "NEEDS_INPUT"  # invalid code
    assert fields["Year of registration"].value is None
    assert fields["Signature of authorised person"].status == "NEEDS_INPUT"
    assert fields["Signature of authorised person"].value is None
    assert fields["Date"].status == "NEEDS_INPUT" and fields["Date"].value is None


async def test_no_form_pages_no_llm_call() -> None:
    llm = FakeLLMClient()
    assert await fd.detect_forms(llm, [page(1, "General conditions")], [], "r1") == []
    assert llm.calls == []


def test_sensitive_label_detection() -> None:
    for label in ("Signature", "Company stamp", "Seal", "Witness 1", "Declaration accepted",
                  "Date", "Signed on", "Authorised signatory"):
        assert fd.is_sensitive(label), label
    for label in ("Date of incorporation", "Designation", "Registration authority"):
        assert not fd.is_sensitive(label), label
