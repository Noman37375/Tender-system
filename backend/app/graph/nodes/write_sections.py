"""write_sections node (PRD 7.3 write_sections).

- First pass: every LLM-written section of the plan (prescribed structure, else PRD 7.4 list).
- Automatic revision: only `sections_to_revise` from the audit, with their findings; sections the
  user edited (`edited_by_user`) are never overwritten automatically.
- Human REQUEST_CHANGES: only the sections the user selected (all non-edited sections when none
  were selected), with the user's notes as instructions. A user-selected section is regenerated
  even if it was edited, because the user asked for it.
- Each pass persists a new proposal version (`version = revision + 1`); sections that were not
  regenerated are carried over unchanged, including their `edited_by_user` flag.

`revision_count` is bumped at node start on every re-run (see `next_revision`), so this node and
the following audit get fresh `agent_steps` rows per revision. It also clears `review_decision`
once consumed, so a later automatic revision is not mistaken for a human request.
"""

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import section_writer
from app.db.models import Proposal as ProposalRow
from app.db.models import ProposalSection as SectionRow
from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.graph.state import TenderState
from app.repositories.results import ResultsRepository
from app.schemas.audit import AuditFinding, AuditReport
from app.schemas.evidence import CompanyEvidence
from app.schemas.proposal import DEFAULT_SECTIONS, ProposalSection
from app.schemas.solution import SolutionDesign
from app.schemas.tender import TenderRequirements

NAME = "write_sections"
FRAME_HEAD = [("cover", "Cover Page", False), ("toc", "Table of Contents", False)]
FRAME_TAIL = [
    ("compliance_annex", "Annex A — Compliance Matrix", False),
    ("forms_annex", "Annex B — Prescribed Forms", False),
]


def next_revision(state: TenderState) -> int:
    """0 on the first pass; previous revision + 1 on every re-run (idempotent on retry)."""
    if state.get("proposal_sections"):
        return int(state.get("revision_count", 0)) + 1
    return 0


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "section"


def section_plan(tender: TenderRequirements) -> list[tuple[str, str, bool]]:
    if not tender.prescribed_structure:
        return list(DEFAULT_SECTIONS)
    seen: set[str] = set()
    body: list[tuple[str, str, bool]] = []
    for title in tender.prescribed_structure:
        key = _slug(title)
        while key in seen:
            key += "_x"
        seen.add(key)
        body.append((key, title, True))
    return FRAME_HEAD + body + FRAME_TAIL


def build_write_context(
    tender_requirements: dict[str, Any],
    company_evidence: dict[str, Any],
    solution_design: dict[str, Any] | None,
) -> section_writer.WriteContext:
    tender = TenderRequirements.model_validate(tender_requirements)
    return section_writer.WriteContext(
        metadata=tender.metadata,
        requirements=tender.requirements,
        evidence=CompanyEvidence.model_validate(company_evidence).items,
        solution=SolutionDesign.model_validate(solution_design) if solution_design else None,
    )


def _findings_by_section(
    report: dict[str, Any] | None, keys: list[str]
) -> dict[str, list[AuditFinding]] | None:
    if not report:
        return None
    grouped: dict[str, list[AuditFinding]] = {}
    for finding in AuditReport.model_validate(report).findings:
        if finding.section_key in keys:
            grouped.setdefault(finding.section_key, []).append(finding)
    return grouped or None


async def work(call: NodeCall) -> NodeOutput:
    state = call.state
    tender = TenderRequirements.model_validate(state["tender_requirements"])
    plan = section_plan(tender)
    order = {key: i for i, (key, _, _) in enumerate(plan)}
    llm_keys = [key for key, _, by_llm in plan if by_llm]
    version = call.revision + 1

    previous: dict[str, SectionRow] = {}
    if call.revision > 0:
        async with call.session() as session:
            repo = ResultsRepository(session)
            prev = await repo.proposal_version(call.organisation_id, call.run_id, call.revision)
            if prev is not None:
                previous = {
                    s.section_key: s for s in await repo.sections(call.organisation_id, prev.id)
                }

    decision = state.get("review_decision") or {}
    instructions: str | None = None
    if not previous:
        targets = llm_keys
        mode = "initial"
    elif decision.get("action") == "REQUEST_CHANGES":
        selected = [str(k) for k in decision.get("sections") or []]
        targets = selected or [k for k in llm_keys if not _edited(previous, k)]
        instructions = decision.get("notes") or None
        mode = "changes"
    else:
        targets = [k for k in state.get("sections_to_revise", []) if not _edited(previous, k)]
        mode = "revision"
    targets = [k for k in llm_keys if k in set(targets)]
    findings = _findings_by_section(state.get("audit_report"), targets) if previous else None

    ctx = build_write_context(
        state["tender_requirements"], state["company_evidence"], state.get("solution_design")
    )
    written_raw = await section_writer.write_sections(
        call.llm,
        targets,
        ctx,
        str(call.run_id),
        findings_by_section=findings,
        user_instructions=instructions,
        concurrency=call.ctx.llm_concurrency,
    )
    written = {
        key: ProposalSection.model_validate(section.model_dump())
        for key, section in written_raw.items()
    }

    rows: list[dict[str, Any]] = []
    for key, old in previous.items():
        if key in written:
            continue
        rows.append(
            {
                "section": ProposalSection(
                    section_key=key,
                    title=old.title,
                    content_md=old.content_md,
                    citations=old.citations,
                    placeholders=old.placeholders,
                ),
                "order_index": old.order_index,
                "edited_by_user": old.edited_by_user,
            }
        )
    for key, section in written.items():
        rows.append(
            {
                "section": section,
                "order_index": order.get(key, len(order)),
                "edited_by_user": False,
            }
        )
    rows.sort(key=lambda r: (r["order_index"], r["section"].section_key))

    async def persist(session: AsyncSession) -> None:
        repo = ResultsRepository(session)
        stale = await repo.proposal_version(call.organisation_id, call.run_id, version)
        if stale is not None:  # retry of this same revision
            await repo.delete_proposal(stale)
        proposal = ProposalRow(
            organisation_id=call.organisation_id,
            run_id=call.run_id,
            version=version,
            status="DRAFT",
        )
        session.add(proposal)
        await session.flush()
        for row in rows:
            section: ProposalSection = row["section"]
            session.add(
                SectionRow(
                    organisation_id=call.organisation_id,
                    proposal_id=proposal.id,
                    section_key=section.section_key,
                    title=section.title,
                    order_index=row["order_index"],
                    content_md=section.content_md,
                    citations=[c.model_dump(mode="json") for c in section.citations],
                    placeholders=list(section.placeholders),
                    edited_by_user=row["edited_by_user"],
                )
            )

    sections_state = {r["section"].section_key: r["section"].model_dump(mode="json") for r in rows}
    return NodeOutput(
        state={
            "proposal_sections": sections_state,
            "revision_count": call.revision,
            "review_decision": None,
        },
        persist=persist,
        output={"version": version, "mode": mode, "regenerated": sorted(written)},
        summary=f"v{version}: {len(written)} sections written ({mode})",
    )


def _edited(previous: dict[str, SectionRow], key: str) -> bool:
    row = previous.get(key)
    return bool(row is not None and row.edited_by_user)


write_sections = graph_node(NAME, revision_from=next_revision)(work)
