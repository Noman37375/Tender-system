"""Graph tests (PRD 16): every route of the TenderIQ graph with fake agents and rules."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    AgentStep,
    AuditReport,
    BidDecision,
    ComplianceRecord,
    Document,
    EvidenceItem,
    MissingItem,
    Proposal,
    ProposalSection,
    Requirement,
    ReviewAction,
    Run,
    RunEvent,
    Tender,
    TenderForm,
)
from app.graph.executor import RunExecutor
from app.schemas.proposal import DEFAULT_SECTIONS
from tests.graph.fakes import Scenario, retry_run, review_run, seed, start_run

LLM_KEYS = [k for k, _, by_llm in DEFAULT_SECTIONS if by_llm]


async def get_run(sm: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> Run:
    async with sm() as s:
        run = await s.get(Run, run_id)
        assert run is not None
        return run


async def rows(sm: async_sessionmaker[AsyncSession], model: type, **where: object) -> list:
    async with sm() as s:
        stmt = select(model)
        for k, v in where.items():
            stmt = stmt.where(getattr(model, k) == v)
        return list((await s.execute(stmt)).scalars())


async def event_types(sm: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> list[str]:
    async with sm() as s:
        result = await s.execute(
            select(RunEvent.type).where(RunEvent.run_id == run_id).order_by(RunEvent.id)
        )
        return list(result.scalars())


async def test_happy_path_waits_for_review_then_approve_completes(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)

    run = await get_run(sessionmaker, run_id)
    assert run.status == "WAITING_REVIEW", run.error
    assert run.current_node == "human_review"
    async with sessionmaker() as s:
        tender = await s.get(Tender, seeded.tender_id)
        assert tender is not None
        assert tender.status == "AWAITING_REVIEW"
        assert tender.title == "Smart City Network"  # metadata persisted
        assert tender.reference_no == "PPRA-42"
        assert tender.submission_deadline is not None

    # domain persistence of every node
    assert len(await rows(sessionmaker, Requirement, tender_id=seeded.tender_id)) == 3
    assert len(await rows(sessionmaker, ComplianceRecord, run_id=run_id)) == 3
    assert len(await rows(sessionmaker, BidDecision, run_id=run_id)) == 1
    forms = {f.form_code: f for f in await rows(sessionmaker, TenderForm, run_id=run_id)}
    assert forms["FORM-2"].fill_status == "SKIPPED_FINANCIAL"
    assert all(f["value"] is None for f in forms["FORM-2"].fields)
    assert forms["FORM-1"].fill_status == "PARTIAL"
    proposals = await rows(sessionmaker, Proposal, run_id=run_id)
    assert [(p.version, p.status) for p in proposals] == [(1, "AUDIT_PASSED")]
    sections = await rows(sessionmaker, ProposalSection, proposal_id=proposals[0].id)
    assert sorted(s.section_key for s in sections) == sorted(LLM_KEYS)
    assert len(await rows(sessionmaker, AuditReport, proposal_id=proposals[0].id)) == 1

    # evidence: codes assigned, EXPIRED never stored, documents marked extracted
    evidence = await rows(sessionmaker, EvidenceItem, organisation_id=seeded.org_id)
    codes = sorted(e.evidence_code for e in evidence)
    assert codes == ["EV-CER-001", "EV-CER-002", "EV-PRJ-001", "EV-PRJ-002"]
    assert {e.verification_status for e in evidence} == {"DOCUMENTED"}
    docs = await rows(sessionmaker, Document, tender_id=None)
    assert all(d.evidence_extracted_at is not None for d in docs)
    state = await executor.state(run_id)
    statuses = {i["evidence_code"]: i["verification_status"] for i in state["company_evidence"]["items"]}
    assert statuses["EV-CER-001"] == "EXPIRED"  # expiry 2029-06-30 < deadline 2030-01-01
    assert statuses["EV-PRJ-001"] == "DOCUMENTED"
    assert any("FORM-1" in m["item"] for m in state["missing_information"])

    # every node wrote a COMPLETED step except the paused human_review
    steps = {(s.node, s.status) for s in await rows(sessionmaker, AgentStep, run_id=run_id)}
    for node in ("ingest", "tender_extract", "company_extract", "compliance", "bid_decision",
                 "solution_design", "form_detection", "write_sections", "audit"):
        assert (node, "COMPLETED") in steps
    assert ("human_review", "RUNNING") in steps

    types = await event_types(sessionmaker, run_id)
    assert types[0] == "run.started"
    assert "audit.result" in types
    assert types[-1] == "run.waiting_review"

    await review_run(executor, seeded, run_id, "APPROVE")
    run = await get_run(sessionmaker, run_id)
    assert run.status == "COMPLETED"
    assert run.finished_at is not None
    async with sessionmaker() as s:
        tender = await s.get(Tender, seeded.tender_id)
        assert tender is not None and tender.status == "APPROVED"
    proposals = await rows(sessionmaker, Proposal, run_id=run_id)
    assert proposals[0].status == "APPROVED"
    actions = await rows(sessionmaker, ReviewAction, run_id=run_id)
    assert [a.action for a in actions] == ["APPROVE"]
    hr = [s for s in await rows(sessionmaker, AgentStep, run_id=run_id) if s.node == "human_review"]
    assert [(s.attempt, s.status) for s in hr] == [(1, "COMPLETED")]  # resumed, not duplicated
    assert (await event_types(sessionmaker, run_id))[-1] == "run.completed"
    assert scenario.calls["write_sections"] == 1


async def test_audit_fail_then_revision_passes(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    scenario.audit_passes.extend([False, True])
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)

    run = await get_run(sessionmaker, run_id)
    assert run.status == "WAITING_REVIEW"
    assert run.revision_count == 1
    assert scenario.written == [LLM_KEYS, ["experience"]]  # only the flagged section
    assert scenario.findings_seen[1] == {"experience": 1}
    proposals = sorted(await rows(sessionmaker, Proposal, run_id=run_id), key=lambda p: p.version)
    assert [(p.version, p.status) for p in proposals] == [(1, "AUDIT_FAILED"), (2, "AUDIT_PASSED")]
    v2 = {s.section_key: s for s in await rows(sessionmaker, ProposalSection, proposal_id=proposals[1].id)}
    assert v2["experience"].content_md.startswith("experience pass 2")
    assert v2["team"].content_md.startswith("team pass 1")  # carried over
    steps = [(s.node, s.revision) for s in await rows(sessionmaker, AgentStep, run_id=run_id)]
    assert ("write_sections", 1) in steps and ("audit", 1) in steps
    state = await executor.state(run_id)
    assert state["audit_report"]["passed"] is True


async def test_audit_fails_twice_goes_to_human_with_flagged_issues(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    scenario.audit_passes.extend([False, False])
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)

    run = await get_run(sessionmaker, run_id)
    assert run.status == "WAITING_REVIEW"
    assert scenario.calls["audit"] == 2  # exactly one automatic revision (D9)
    assert scenario.calls["write_sections"] == 2
    state = await executor.state(run_id)
    assert state["audit_report"]["passed"] is False
    assert state["sections_to_revise"] == ["experience"]
    async with sessionmaker() as s:
        events = (
            await s.execute(
                select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id)
            )
        ).scalars().all()
    assert events[-1].type == "run.waiting_review"
    assert events[-1].payload == {"audit_passed": False}


async def test_no_bid_still_continues_and_decision_is_stored(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    scenario.recommendation = "NO_BID"
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)

    run = await get_run(sessionmaker, run_id)
    assert run.status == "WAITING_REVIEW"
    decisions = await rows(sessionmaker, BidDecision, run_id=run_id)
    assert decisions[0].recommendation == "NO_BID"
    reqs = {r.id: r.req_code for r in await rows(sessionmaker, Requirement, tender_id=seeded.tender_id)}
    assert [reqs[i] for i in decisions[0].blocking_requirements] == ["ELG-001"]
    assert decisions[0].reasons == ["Recommendation is NO_BID"]
    missing = await rows(sessionmaker, MissingItem, run_id=run_id)
    assert [m.severity for m in missing] == ["BLOCKER"]
    assert scenario.calls["write_sections"] == 1  # proposal still drafted
    state = await executor.state(run_id)
    assert any(w.startswith("NO_BID") for w in state["warnings"])


async def test_node_failure_then_retry_resumes_from_checkpoint(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    scenario.fail_once.add("compliance")
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)

    run = await get_run(sessionmaker, run_id)
    assert run.status == "FAILED"
    assert "simulated failure in compliance" in (run.error or "")
    async with sessionmaker() as s:
        tender = await s.get(Tender, seeded.tender_id)
        assert tender is not None and tender.status == "FAILED"
    types = await event_types(sessionmaker, run_id)
    assert "node.failed" in types and types[-1] == "run.failed"

    await retry_run(executor, seeded, run_id)
    run = await get_run(sessionmaker, run_id)
    assert run.status == "WAITING_REVIEW", run.error
    # upstream nodes were not re-run
    assert scenario.calls["ingest"] == 3  # 3 documents, once each
    assert scenario.calls["tender_extract"] == 1
    assert scenario.calls["company_extract"] == 2  # 2 company documents, once each
    assert scenario.calls["compliance"] == 2
    steps = sorted(
        (s.attempt, s.status)
        for s in await rows(sessionmaker, AgentStep, run_id=run_id)
        if s.node == "compliance"
    )
    assert steps == [(1, "FAILED"), (2, "COMPLETED")]
    assert len(await rows(sessionmaker, ComplianceRecord, run_id=run_id)) == 3


async def test_parallel_branch_failure_retry_keeps_sibling_result(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    scenario.fail_once.add("company_extract")
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)
    assert (await get_run(sessionmaker, run_id)).status == "FAILED"

    await retry_run(executor, seeded, run_id)
    assert (await get_run(sessionmaker, run_id)).status == "WAITING_REVIEW"
    assert scenario.calls["tender_extract"] == 1
    # failed attempt persisted nothing; the retry assigned codes from 001
    codes = sorted(
        e.evidence_code for e in await rows(sessionmaker, EvidenceItem, organisation_id=seeded.org_id)
    )
    assert codes == ["EV-CER-001", "EV-CER-002", "EV-PRJ-001", "EV-PRJ-002"]


async def test_request_changes_regenerates_only_selected_and_keeps_user_edits(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)
    assert (await get_run(sessionmaker, run_id)).status == "WAITING_REVIEW"

    # the user edits two sections during review
    async with sessionmaker() as s, s.begin():
        v1 = (await s.execute(select(Proposal).where(Proposal.run_id == run_id))).scalar_one()
        for key in ("team", "support"):
            sec = (
                await s.execute(
                    select(ProposalSection).where(
                        ProposalSection.proposal_id == v1.id, ProposalSection.section_key == key
                    )
                )
            ).scalar_one()
            sec.content_md = f"user text for {key}"
            sec.edited_by_user = True

    await review_run(
        executor, seeded, run_id, "REQUEST_CHANGES", sections=["methodology", "team"], notes="shorter"
    )
    run = await get_run(sessionmaker, run_id)
    assert run.status == "WAITING_REVIEW"
    assert run.revision_count == 1
    assert scenario.written[1] == ["methodology", "team"]  # user asked for team explicitly
    assert scenario.instructions[1] == "shorter"
    proposals = sorted(await rows(sessionmaker, Proposal, run_id=run_id), key=lambda p: p.version)
    assert [p.version for p in proposals] == [1, 2]
    v2 = {s.section_key: s for s in await rows(sessionmaker, ProposalSection, proposal_id=proposals[1].id)}
    assert v2["methodology"].content_md.startswith("methodology pass 2")
    assert v2["team"].content_md.startswith("team pass 2") and not v2["team"].edited_by_user
    assert v2["support"].content_md == "user text for support" and v2["support"].edited_by_user
    assert v2["executive_summary"].content_md.startswith("executive_summary pass 1")
    assert len(v2) == len(LLM_KEYS)

    # REQUEST_CHANGES without a selection regenerates everything except user edits
    await review_run(executor, seeded, run_id, "REQUEST_CHANGES")
    assert "support" not in scenario.written[2]
    assert len(scenario.written[2]) == len(LLM_KEYS) - 1
    assert scenario.instructions[2] is None

    await review_run(executor, seeded, run_id, "APPROVE")
    assert (await get_run(sessionmaker, run_id)).status == "COMPLETED"
    actions = [a.action for a in await rows(sessionmaker, ReviewAction, run_id=run_id)]
    assert sorted(actions) == ["APPROVE", "REQUEST_CHANGES", "REQUEST_CHANGES"]
    hr = sorted(
        (s.revision, s.status)
        for s in await rows(sessionmaker, AgentStep, run_id=run_id)
        if s.node == "human_review"
    )
    assert hr == [(0, "COMPLETED"), (1, "COMPLETED"), (2, "COMPLETED")]


async def test_budget_exceeded_stops_before_next_node(
    executor: RunExecutor,
    scenario: Scenario,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import run_service

    monkeypatch.setattr(run_service, "budget_from_settings", lambda: Decimal("0.50"))
    scenario.cost_per_ingest = Decimal("1.25")
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)

    run = await get_run(sessionmaker, run_id)
    assert run.status == "FAILED"
    assert (run.error or "").startswith("BUDGET_EXCEEDED")
    assert run.cost_usd == Decimal("3.7500")  # 3 documents x 1.25, all inside ingest
    assert run.tokens_in == 300
    # stopped before any further LLM work
    assert scenario.calls["tender_extract"] == 0
    assert scenario.calls["company_extract"] == 0
    failed = [s for s in await rows(sessionmaker, AgentStep, run_id=run_id) if s.status == "FAILED"]
    assert sorted(s.node for s in failed) == ["company_extract", "tender_extract"]
    assert all((s.error or "").startswith("BUDGET_EXCEEDED") for s in failed)
    ingest = [s for s in await rows(sessionmaker, AgentStep, run_id=run_id) if s.node == "ingest"]
    assert ingest[0].cost_usd == Decimal("3.7500")


async def test_budget_error_from_llm_adapter_fails_run(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    scenario.budget_error_in = "solution_design"
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)
    run = await get_run(sessionmaker, run_id)
    assert run.status == "FAILED"
    assert run.error == "BUDGET_EXCEEDED: adapter refused the next call"


async def test_compliance_invariant_fails_node(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    scenario.drop_match_for = "TEC-001"
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)
    run = await get_run(sessionmaker, run_id)
    assert run.status == "FAILED"
    assert "ComplianceInvariantError" in (run.error or "")
    assert await rows(sessionmaker, ComplianceRecord, run_id=run_id) == []


async def test_addendum_supersedes_requirements(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    scenario.with_addendum_changes = True
    seeded = await seed(sessionmaker, with_addendum=True)
    run_id = await start_run(executor, seeded)
    assert (await get_run(sessionmaker, run_id)).status == "WAITING_REVIEW"

    reqs = {r.req_code: r for r in await rows(sessionmaker, Requirement, tender_id=seeded.tender_id)}
    assert set(reqs) == {"ELG-001", "EXP-001", "TEC-001", "TEC-001-A1", "DEL-001"}
    assert reqs["TEC-001"].superseded_by == reqs["TEC-001-A1"].id
    assert reqs["EXP-001"].superseded_by == reqs["EXP-001"].id  # deleted by the addendum
    assert reqs["TEC-001-A1"].superseded_by is None
    records = await rows(sessionmaker, ComplianceRecord, run_id=run_id)
    assert len(records) == 3  # one per active requirement
    state = await executor.state(run_id)
    assert state["tender_requirements"]["metadata"]["submission_deadline"] == "2030-02-01"


async def test_second_run_reuses_extracted_evidence(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    seeded = await seed(sessionmaker)
    first = await start_run(executor, seeded)
    await review_run(executor, seeded, first, "APPROVE")
    assert scenario.calls["company_extract"] == 2

    second = await start_run(executor, seeded)
    assert (await get_run(sessionmaker, second)).status == "WAITING_REVIEW"
    assert scenario.calls["company_extract"] == 2  # documents extracted once
    evidence = await rows(sessionmaker, EvidenceItem, organisation_id=seeded.org_id)
    assert len(evidence) == 4
    # requirements were re-extracted in place, still referenced by the first run's records
    assert len(await rows(sessionmaker, Requirement, tender_id=seeded.tender_id)) == 3
    assert len(await rows(sessionmaker, ComplianceRecord, run_id=first)) == 3
    assert len(await rows(sessionmaker, ComplianceRecord, run_id=second)) == 3


async def test_new_evidence_codes_continue_after_org_maximum(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    seeded = await seed(sessionmaker)
    first = await start_run(executor, seeded)
    await review_run(executor, seeded, first, "APPROVE")
    other = await seed(sessionmaker, org_id=seeded.org_id, user_id=seeded.user_id)
    await start_run(executor, other)
    codes = sorted(
        e.evidence_code for e in await rows(sessionmaker, EvidenceItem, organisation_id=seeded.org_id)
    )
    assert codes[-1] == "EV-PRJ-004"
    assert "EV-CER-004" in codes


async def test_cancel_waiting_run(
    executor: RunExecutor, scenario: Scenario, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    seeded = await seed(sessionmaker)
    run_id = await start_run(executor, seeded)
    await executor.cancel(seeded.org_id, run_id)
    run = await get_run(sessionmaker, run_id)
    assert run.status == "CANCELLED"
    steps = [s for s in await rows(sessionmaker, AgentStep, run_id=run_id) if s.node == "human_review"]
    assert steps[0].status == "FAILED" and steps[0].error == "cancelled"
    assert (await event_types(sessionmaker, run_id))[-1] == "run.cancelled"
    async with sessionmaker() as s:
        tender = await s.get(Tender, seeded.tender_id)
        assert tender is not None and tender.status == "DRAFT"
