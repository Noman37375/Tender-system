from typing import Any

import pytest

from app.agents import auditor, bid_reasons
from app.agents import section_writer as sw
from app.llm.adapter import BudgetExceededError
from app.llm.fake import FakeLLMClient
from app.schemas.audit import AuditFinding, FindingType
from app.schemas.compliance import BidDecision, ComplianceRecord, ComplianceStatus
from app.schemas.evidence import EvidenceCategory as EC
from app.schemas.proposal import ProposalSection
from app.schemas.solution import SolutionDesign
from app.schemas.tender import ReqCategory as RC
from app.schemas.tender import TenderMetadata
from tests.unit.agents.builders import ev, req

PLACEHOLDER = "[CLIENT INPUT REQUIRED: commercial content belongs in financial proposal]"


def ctx() -> sw.WriteContext:
    return sw.WriteContext(
        metadata=TenderMetadata(title="HRMIS Tender", procuring_entity="Punjab IT Board"),
        requirements=[
            req("TEC-001", "Single sign-on"),
            req("PER-001", "Project manager with PMP", RC.PERSONNEL),
            req("EXP-001", "Three similar projects", RC.EXPERIENCE),
        ],
        evidence=[
            ev("EV-PER-001", EC.PERSONNEL, "Jane Doe, PMP, 12 years"),
            ev("EV-PRJ-001", EC.PROJECT, "HRMIS for the Punjab IT Board"),
            ev("EV-CAP-001", EC.CAPABILITY, "SSO integration"),
        ],
        solution=SolutionDesign(
            approach_summary="Agile",
            architecture_description="Three tiers",
            architecture_components=[],
            requirement_traceability={"TEC-001": "Keycloak"},
            phases=[],
            testing_strategy="Automated testing",
            deployment_strategy="Blue/green",
            support_model="24x7 helpdesk",
            assumptions=["Client provides servers"],
            risks=[],
            capability_gaps=[],
        ),
        glossary={"HRMIS": "Human Resource Management Information System"},
    )


def section_answer(key: str, content: str) -> dict[str, Any]:
    return {
        "section_key": "wrong-key",
        "title": "Wrong",
        "content_md": content,
        "citations": [{"claim": "Jane Doe is PMP", "evidence_codes": ["EV-PER-001"]}],
        "placeholders": [],
    }


async def test_section_postprocessing_pricing_and_placeholders() -> None:
    content = (
        "### Team\nJane Doe is a certified PMP. The daily rate is PKR 50,000 per day.\n\n"
        "[CLIENT INPUT REQUIRED: CV of the database administrator]"
    )
    llm = FakeLLMClient().add("write_sections", section_answer("team", content))
    section, findings = await sw.write_section_with_findings(
        llm, "team", "Team Composition", ctx(), run_id="r1"
    )
    assert section.section_key == "team" and section.title == "Team Composition"
    assert "PKR 50,000" not in section.content_md
    assert PLACEHOLDER in section.content_md
    assert section.placeholders == [
        PLACEHOLDER,
        "[CLIENT INPUT REQUIRED: CV of the database administrator]",
    ]
    assert [f.type for f in findings] == [FindingType.PRICING_LEAK]


async def test_context_pack_is_section_specific() -> None:
    llm = FakeLLMClient().on("write_sections", lambda s, u, schema: section_answer("x", "Text."))
    await sw.write_section(llm, "team", "Team Composition", ctx(), run_id="r1")
    user = llm.calls[0].user
    assert "EV-PER-001" in user and "PER-001" in user
    assert "EV-PRJ-001" not in user and "EV-CAP-001" not in user and "TEC-001" not in user
    assert "Punjab IT Board" in user  # tender entity (wrapped as untrusted data)
    assert "SECURITY AND INTEGRITY RULES" in llm.calls[0].system
    assert "Punjab IT Board" not in llm.calls[0].system  # document data never in system prompt

    await sw.write_section(llm, "experience", "Relevant Project Experience", ctx(), run_id="r1")
    user = llm.calls[1].user
    assert "EV-PRJ-001" in user and "EXP-001" in user and "EV-PER-001" not in user


async def test_write_sections_skips_template_sections_and_passes_feedback() -> None:
    llm = FakeLLMClient().on("write_sections", lambda s, u, schema: section_answer("x", "Text."))
    finding = AuditFinding(
        type=FindingType.UNSUPPORTED_CLAIM,
        severity="MAJOR",
        section_key="support",
        description="Claims ISO 20000 without evidence",
        suggested_fix="Remove the claim",
    )
    out = await sw.write_sections(
        llm,
        ["cover", "toc", "support", "testing_qa", "compliance_annex", "forms_annex", "support"],
        ctx(),
        run_id="r1",
        findings_by_section={"support": [finding]},
    )
    assert list(out) == ["support", "testing_qa"]
    assert len(llm.calls) == 2
    support_call = next(c for c in llm.calls if "key: support" in c.user)
    assert "Claims ISO 20000 without evidence" in support_call.user
    assert all(c.model_tier == "strong" for c in llm.calls)


# ------------------------------------------------------------------ audit
def finding(sev: str, key: str | None, ftype: FindingType = FindingType.UNSUPPORTED_CLAIM,
            desc: str = "problem") -> AuditFinding:
    return AuditFinding(type=ftype, severity=sev, section_key=key, description=desc,  # type: ignore[arg-type]
                        suggested_fix="fix")


def test_build_report_pass_fail() -> None:
    assert auditor.build_report([]).passed is True
    minor_only = auditor.build_report([finding("MINOR", "team")])
    assert minor_only.passed is True and minor_only.sections_to_revise == []
    report = auditor.build_report(
        [finding("MAJOR", "team"), finding("BLOCKER", "support"), finding("MAJOR", "team"),
         finding("BLOCKER", None)]
    )
    assert report.passed is False
    assert report.sections_to_revise == ["team", "support"]
    assert len(report.findings) == 4


def _section(key: str) -> ProposalSection:
    return ProposalSection(section_key=key, title=key, content_md="We are great.", citations=[],
                           placeholders=[])


async def test_review_filters_llm_findings() -> None:
    automated = [finding("MAJOR", "team", desc="Unsupported claim: We are great.")]
    llm = FakeLLMClient().add(
        "audit",
        {
            "findings": [
                finding("MAJOR", "team", desc="Unsupported claim: We are great.").model_dump(),
                finding("MAJOR", "team", FindingType.INVALID_CITATION).model_dump(),
                finding("BLOCKER", "unknown_section").model_dump(),
                finding("MAJOR", "support", FindingType.CONTRADICTION,
                        "Team says 5 staff, support says 10").model_dump(),
            ]
        },
    )
    sections = {"team": _section("team"), "support": _section("support")}
    out = await auditor.review(llm, sections, [req("TEC-001", "x")], [], automated, run_id="r1")
    assert len(llm.calls) == 1 and llm.calls[0].schema == "AuditFindingList"
    assert [(f.type, f.section_key) for f in out] == [(FindingType.CONTRADICTION, "support")]


async def test_review_batches_large_proposals() -> None:
    big = {f"s{i}": ProposalSection(section_key=f"s{i}", title="t", content_md="x" * 30_000,
                                     citations=[], placeholders=[]) for i in range(3)}
    llm = FakeLLMClient().on("audit", lambda s, u, schema: {"findings": []})
    assert await auditor.review(llm, big, [], [], [], run_id="r1") == []
    assert len(llm.calls) == 3
    assert await auditor.review(FakeLLMClient(), {}, [], [], [], run_id="r1") == []


# ------------------------------------------------------------------ bid reasons
DECISION = BidDecision(recommendation="NO_BID", eligibility_passed=False,
                       blocking_req_codes=["FIN-001"], reasons=[])
RECORDS = [
    ComplianceRecord(req_code="FIN-001", status=ComplianceStatus.NON_COMPLIANT, evidence_codes=[],
                     llm_proposed_status=ComplianceStatus.NON_COMPLIANT, rule_applied="R3",
                     rationale="r", gap_description="Turnover below PKR 50M"),
]


async def test_bid_reasons_pads_to_three_and_keeps_order() -> None:
    llm = FakeLLMClient().add("bid_decision", {"reasons": ["Turnover is below the minimum."]})
    reasons = await bid_reasons.explain(llm, DECISION, RECORDS, run_id="r1")
    assert reasons[0] == "Turnover is below the minimum."
    assert 3 <= len(reasons) <= 7
    assert "FIN-001" in llm.calls[0].user and "NO_BID" in llm.calls[0].user


async def test_bid_reasons_accepts_bid_decision_fixture_and_falls_back() -> None:
    llm = FakeLLMClient().add("bid_decision", DECISION.model_copy(update={"reasons": list("abcdefghi")}))
    assert len(await bid_reasons.explain(llm, DECISION, RECORDS, run_id="r1")) == 7

    failing = FakeLLMClient()  # nothing queued -> AssertionError -> fallback reasons
    reasons = await bid_reasons.explain(failing, DECISION, RECORDS, run_id="r1")
    assert reasons[0].startswith("Recommendation: do not bid")
    assert any("FIN-001" in r for r in reasons)


async def test_bid_reasons_budget_error_propagates() -> None:
    def boom(s: str, u: str, schema: type) -> dict:
        raise BudgetExceededError("over")

    with pytest.raises(BudgetExceededError):
        await bid_reasons.explain(FakeLLMClient().on("bid_decision", boom), DECISION, RECORDS, "r1")
