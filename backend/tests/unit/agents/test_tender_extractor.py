import re

from app.agents import tender_extractor as te
from app.agents._common import build_windows
from app.llm.fake import FakeLLMClient
from app.schemas.common import Confidence
from app.schemas.tender import AddendumChanges, ReqCategory, TenderRequirements
from tests.unit.agents.builders import page, req_dict, tender_answer

LONG = "lorem ipsum " * 2500  # ~30k chars, ~7.5k tokens -> one page per window pair


def test_windows_are_page_aligned_and_respect_document_boundaries() -> None:
    pages = [page(1, LONG), page(2, LONG), page(3, "short"), page(1, "other doc", doc="doc-b")]
    windows = build_windows(pages, max_tokens=12_000)
    assert [[(p.document_id, p.page_no) for p in w] for w in windows] == [
        [("doc-tender", 1)],
        [("doc-tender", 2), ("doc-tender", 3)],
        [("doc-b", 1)],
    ]


def test_merge_dedupes_within_category_keeps_higher_confidence_and_mandatory() -> None:
    a = TenderRequirements.model_validate(
        tender_answer(
            [
                req_dict("The bidder must be registered with SECP.", confidence="MEDIUM",
                         mandatory=False),
                req_dict("The bidder must be registered with SECP", "SUBMISSION"),
            ]
        )
    )
    b = TenderRequirements.model_validate(
        tender_answer([req_dict("the bidder must be registered with SECP!", confidence="HIGH")])
    )
    merged = te.merge_requirements([a.requirements, b.requirements])
    assert len(merged) == 2  # same text in another category is NOT merged
    elg = merged[0]
    assert elg.category == ReqCategory.ELIGIBILITY
    assert elg.confidence == Confidence.HIGH
    assert elg.is_mandatory is True


def test_merge_never_merges_different_thresholds() -> None:
    crit = {"metric": "annual_turnover", "op": ">=", "value": 50_000_000, "unit": "PKR"}
    crit2 = {**crit, "value": 80_000_000}
    t = TenderRequirements.model_validate(
        tender_answer(
            [
                req_dict("Average annual turnover of at least PKR 50 million", "FINANCIAL",
                         criterion=crit),
                req_dict("Average annual turnover of at least PKR 80 million", "FINANCIAL",
                         criterion=crit2),
            ]
        )
    )
    assert len(te.merge_requirements([t.requirements])) == 2


def test_assign_codes_per_category_and_continuation() -> None:
    t = TenderRequirements.model_validate(
        tender_answer(
            [
                req_dict("a", "ELIGIBILITY"),
                req_dict("b", "TECHNICAL"),
                req_dict("c", "ELIGIBILITY"),
                req_dict("d", "EVALUATION"),
            ]
        )
    )
    coded = te.assign_codes(t.requirements)
    assert [r.req_code for r in coded] == ["ELG-001", "TEC-001", "ELG-002", "EVL-001"]
    more = te.assign_codes(t.requirements[:1], existing_codes=["ELG-001", "ELG-007", "TEC-002"])
    assert more[0].req_code == "ELG-008"


async def test_extract_single_window_skips_reduce_and_verifies_quotes() -> None:
    pages = [
        page(1, "Eligibility. The bidder must be registered with SECP. Bid security is required."),
        page(2, "Technical. The system shall support single sign-on."),
    ]
    llm = FakeLLMClient().add(
        "tender_extract",
        tender_answer(
            [
                req_dict("Registered with SECP", quote="The bidder must be registered with SECP."),
                req_dict("Support SSO", "TECHNICAL", page_no=2,
                         quote="The system shall support single sign-on."),
                req_dict("Hallucinated item", "TECHNICAL", page_no=2,
                         quote="The system shall run on quantum hardware."),
            ],
            title="HRMIS",
        ),
    )
    result = await te.extract_tender(llm, pages, run_id="r1")
    assert len(llm.calls_for("tender_extract")) == 1  # no reduce for one window
    call = llm.calls[0]
    assert call.schema == "TenderRequirements" and call.model_tier == "fast"
    assert "SECURITY AND INTEGRITY RULES" in call.system
    assert '<document id="doc-tender" page="1">' in call.user
    codes = [r.req_code for r in result.requirements]
    assert codes == ["ELG-001", "TEC-001", "TEC-002"]
    by_code = {r.req_code: r for r in result.requirements}
    assert by_code["ELG-001"].confidence == Confidence.HIGH
    assert by_code["TEC-002"].confidence == Confidence.LOW  # never dropped
    assert any("TEC-002" in w and "could not be verified" in w for w in result.extraction_warnings)
    assert result.metadata.title == "HRMIS"


async def test_extract_multi_window_map_merge_reduce() -> None:
    p1 = "The bidder must be registered with SECP. " + LONG
    p2 = "The bidder must be registered with SECP. Must hold ISO 9001. " + LONG
    pages = [page(1, p1), page(2, p2)]

    def respond(system: str, user: str, schema: type) -> dict:
        if schema is te.TenderReduceResult:
            assert "candidate-requirements" in user
            return {
                "merge_groups": [[0, 1], [0, 2]],  # second group mixes categories -> refused
                "metadata": {"title": "Reduced title", "scope_summary": "", "sources": []},
                "prescribed_structure": ["Approach", "Team"],
                "extraction_warnings": ["deadline conflict"],
            }
        page_no = int(re.search(r'page="(\d+)"', user).group(1))  # type: ignore[union-attr]
        if page_no == 1:
            return tender_answer(
                [req_dict("Registered with SECP", quote="The bidder must be registered with SECP.")]
            )
        return tender_answer(
            [
                req_dict("Registration with the SECP", page_no=2, confidence="MEDIUM",
                         quote="The bidder must be registered with SECP."),
                req_dict("ISO 9001 certificate", "CERTIFICATION", page_no=2,
                         quote="Must hold ISO 9001."),
            ]
        )

    llm = FakeLLMClient().on("tender_extract", respond)
    result = await te.extract_tender(llm, pages, run_id="r1")
    schemas = [c.schema for c in llm.calls_for("tender_extract")]
    assert schemas.count("TenderRequirements") == 2 and schemas[-1] == "TenderReduceResult"
    assert [r.req_code for r in result.requirements] == ["ELG-001", "CER-001"]
    assert result.requirements[0].confidence == Confidence.HIGH
    assert result.metadata.title == "Reduced title"
    assert result.prescribed_structure == ["Approach", "Team"]
    assert "deadline conflict" in result.extraction_warnings
    assert any("incompatible" in w for w in result.extraction_warnings)


async def test_reduce_answer_accepts_a_tender_requirements_fixture() -> None:
    """Graph tests may queue TenderRequirements dicts for every tender_extract call."""
    parsed = te.TenderReduceResult.model_validate(tender_answer([req_dict("x")], title="T"))
    assert parsed.merge_groups == [] and parsed.metadata and parsed.metadata.title == "T"


async def test_apply_addendum_modify_add_delete() -> None:
    current = TenderRequirements.model_validate(
        tender_answer(
            [
                req_dict("Turnover PKR 50M", "FINANCIAL", code="FIN-001"),
                req_dict("Support SSO", "TECHNICAL", code="TEC-001"),
                req_dict("Hard copy submission", "SUBMISSION", code="SUB-001"),
            ]
        )
    )
    add_page = page(1, "Clause 5 amended: turnover PKR 30 million. New: system must support MFA. "
                       "Clause 9 deleted.", doc="doc-add")
    llm = FakeLLMClient().add(
        "tender_extract",
        {
            "modified": [
                req_dict("Turnover PKR 30M", "FINANCIAL", code="FIN-001", doc="doc-add",
                         quote="Clause 5 amended: turnover PKR 30 million."),
                req_dict("Unknown change", "TECHNICAL", code="TEC-099", doc="doc-add",
                         quote="New: system must support MFA."),
            ],
            "added": [
                req_dict("Support MFA", "TECHNICAL", doc="doc-add",
                         quote="New: system must support MFA."),
            ],
            "deleted_req_codes": ["SUB-001", "XXX-404"],
            "deletion_sources": [src_dict("Clause 9 deleted.")],
            "metadata_changes": {"submission_deadline": "2026-12-01", "bogus": "x"},
        },
    )
    changes = await te.apply_addendum(llm, current, [add_page], run_id="r1")
    assert llm.calls[0].schema == "AddendumChanges"
    assert [m.req_code for m in changes.modified] == ["FIN-001"]
    assert [a.req_code for a in changes.added] == ["TEC-002", "TEC-003"]  # unknown -> added
    assert changes.deleted_req_codes == ["SUB-001"]
    assert changes.metadata_changes == {"submission_deadline": "2026-12-01"}

    updated = te.apply_changes(current, changes)
    codes = {r.req_code: r for r in updated.requirements}
    assert "SUB-001" not in codes
    assert codes["FIN-001"].description == "Turnover PKR 30M"
    assert {"TEC-001", "TEC-002", "TEC-003"} <= set(codes)
    assert updated.metadata.submission_deadline == "2026-12-01"


def src_dict(quote: str) -> dict:
    return {"document_id": "doc-add", "page": 1, "quote": quote}


async def test_apply_addendum_without_pages_is_noop() -> None:
    current = TenderRequirements.model_validate(tender_answer([]))
    assert await te.apply_addendum(FakeLLMClient(), current, [], "r1") == AddendumChanges()
