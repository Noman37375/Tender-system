"""write_sections, one call per section (PRD 7.3, prompt A.8). OWNER: agents agent.

LLM calls: node="write_sections", schema ProposalSection, prompt "write_section@1", strong
tier, one call per LLM-written section, in parallel under a semaphore. Template sections
(cover, toc, compliance_annex, forms_annex) are never sent to the LLM.

Context pack per section (PRD 7.4 primary inputs): only that section's relevant requirements,
evidence items (code, category, description, attributes, status) and solution fragments.

Post-processing in code:
- section_key / title forced to the requested ones;
- pricing guard (app.rules.pricing_guard.scan) replaces price sentences with the placeholder;
- placeholders re-extracted from the cleaned text (app.rules.citation_checker).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.agents._common import TEMP_WRITE, evidence_view, gather_limited, requirement_view
from app.llm.adapter import LLMClient
from app.prompts.loader import load_prompt, to_json, wrap_data
from app.rules import citation_checker, pricing_guard
from app.schemas.audit import AuditFinding
from app.schemas.evidence import EvidenceCategory, EvidenceItem, VerificationStatus
from app.schemas.proposal import DEFAULT_SECTIONS, ProposalSection
from app.schemas.solution import SolutionDesign
from app.schemas.tender import ReqCategory, Requirement, TenderMetadata

log = structlog.get_logger(__name__)

NODE = "write_sections"
NON_LLM_SECTIONS = {key for key, _, by_llm in DEFAULT_SECTIONS if not by_llm}
SECTION_TITLES = {key: title for key, title, _ in DEFAULT_SECTIONS}

MAX_REQUIREMENTS = 40
MAX_EVIDENCE = 25

SECTION_PURPOSE: dict[str, str] = {
    "executive_summary": "Summarise the bid: understanding of the need, the proposed solution "
    "and the strongest documented credentials.",
    "understanding": "Show a precise understanding of the scope and the technical and "
    "deliverable requirements.",
    "company_profile": "Present the company: registration, capabilities, certifications and "
    "financial standing, strictly from evidence.",
    "technical_solution": "Describe the proposed technical solution and how it meets each "
    "technical requirement.",
    "architecture": "Describe the solution architecture and its components.",
    "scope_of_work": "Set out the scope of work and every deliverable.",
    "methodology": "Explain the implementation methodology phase by phase.",
    "timeline": "Present the project timeline (phases, durations, dependencies) as a table.",
    "team": "Present the proposed team and how it meets the personnel requirements.",
    "experience": "Present relevant completed projects that match the experience requirements.",
    "testing_qa": "Describe testing and quality assurance.",
    "deployment": "Describe deployment, installation and commissioning.",
    "support": "Describe support, maintenance and service levels.",
    "assumptions": "List assumptions, dependencies and key risks with mitigations.",
}
GENERIC_PURPOSE = "Address this section of the tender's prescribed structure."


@dataclass
class WriteContext:
    metadata: TenderMetadata
    requirements: list[Requirement]
    evidence: list[EvidenceItem]
    solution: SolutionDesign | None
    glossary: dict[str, str] = field(default_factory=dict)


# ------------------------------------------------------------------ context packs
def _reqs(
    ctx: WriteContext, *cats: ReqCategory, keywords: tuple[str, ...] = ()
) -> list[Requirement]:
    out = [r for r in ctx.requirements if r.category in cats]
    if keywords:
        out += [
            r
            for r in ctx.requirements
            if r not in out and any(k in r.description.lower() for k in keywords)
        ]
    out.sort(key=lambda r: not r.is_mandatory)  # mandatory first, stable otherwise
    return out[:MAX_REQUIREMENTS]


def _evidence(ctx: WriteContext, *cats: EvidenceCategory) -> list[EvidenceItem]:
    out = [e for e in ctx.evidence if e.category in cats]
    rank = {
        VerificationStatus.DOCUMENTED: 0,
        VerificationStatus.SELF_DECLARED: 1,
        VerificationStatus.UNVERIFIED: 2,
        VerificationStatus.EXPIRED: 3,
    }
    out.sort(key=lambda e: rank[e.verification_status])
    return out[:MAX_EVIDENCE]


def _sol(ctx: WriteContext, *keys: str) -> dict[str, Any]:
    if ctx.solution is None:
        return {}
    dumped = ctx.solution.model_dump(mode="json")
    return {k: dumped[k] for k in keys if k in dumped}


R = ReqCategory
E = EvidenceCategory

_PackFn = Callable[[WriteContext], tuple[list[Requirement], list[EvidenceItem], dict[str, Any]]]

PACKS: dict[str, _PackFn] = {
    "executive_summary": lambda c: (
        [r for r in c.requirements if r.is_mandatory][:MAX_REQUIREMENTS],
        _evidence(c, E.PROJECT, E.CERTIFICATION, E.CAPABILITY, E.COMPANY_REGISTRATION)[:10],
        _sol(c, "approach_summary"),
    ),
    "understanding": lambda c: (_reqs(c, R.TECHNICAL, R.DELIVERABLE), [], {}),
    "company_profile": lambda c: (
        _reqs(c, R.ELIGIBILITY, R.FINANCIAL, R.CERTIFICATION),
        _evidence(
            c,
            E.COMPANY_REGISTRATION,
            E.TAX_REGISTRATION,
            E.CAPABILITY,
            E.FINANCIAL,
            E.CERTIFICATION,
            E.PARTNERSHIP,
        ),
        {},
    ),
    "technical_solution": lambda c: (
        _reqs(c, R.TECHNICAL),
        _evidence(c, E.CAPABILITY),
        _sol(
            c,
            "approach_summary",
            "architecture_description",
            "requirement_traceability",
            "capability_gaps",
        ),
    ),
    "architecture": lambda c: (
        _reqs(c, R.TECHNICAL),
        _evidence(c, E.CAPABILITY),
        _sol(c, "architecture_description", "architecture_components"),
    ),
    "scope_of_work": lambda c: (_reqs(c, R.DELIVERABLE), [], _sol(c, "phases")),
    "methodology": lambda c: ([], [], _sol(c, "approach_summary", "phases")),
    "timeline": lambda c: (
        _reqs(c, keywords=("week", "month", "days", "timeline", "schedule", "milestone")),
        [],
        _sol(c, "phases"),
    ),
    "team": lambda c: (_reqs(c, R.PERSONNEL), _evidence(c, E.PERSONNEL), {}),
    "experience": lambda c: (_reqs(c, R.EXPERIENCE), _evidence(c, E.PROJECT), {}),
    "testing_qa": lambda c: (
        _reqs(c, keywords=("test", "quality", "acceptance", "uat", "qa")),
        [],
        _sol(c, "testing_strategy"),
    ),
    "deployment": lambda c: (
        _reqs(c, keywords=("deploy", "install", "commission", "migrat", "go-live", "training")),
        [],
        _sol(c, "deployment_strategy"),
    ),
    "support": lambda c: (
        _reqs(c, keywords=("support", "maintenance", "warranty", "sla", "helpdesk", "help desk")),
        [],
        _sol(c, "support_model"),
    ),
    "assumptions": lambda c: ([], [], _sol(c, "assumptions", "risks", "capability_gaps")),
}


def _generic_pack(c: WriteContext) -> tuple[list[Requirement], list[EvidenceItem], dict[str, Any]]:
    return (
        _reqs(c, R.TECHNICAL, R.DELIVERABLE, R.EVALUATION),
        _evidence(c, E.CAPABILITY, E.PROJECT),
        _sol(c, "approach_summary", "requirement_traceability"),
    )


def context_pack(
    section_key: str, ctx: WriteContext
) -> tuple[list[Requirement], list[EvidenceItem], dict[str, Any]]:
    return PACKS.get(section_key, _generic_pack)(ctx)


def section_title(section_key: str) -> str:
    return SECTION_TITLES.get(section_key, section_key.replace("_", " ").title())


# ------------------------------------------------------------------ writing
def postprocess(
    section_key: str, title: str, raw: ProposalSection
) -> tuple[ProposalSection, list[AuditFinding]]:
    """Pricing guard first (it inserts placeholders), then extract every placeholder."""
    pricing = pricing_guard.scan(section_key, raw.content_md)
    placeholders = citation_checker.extract_placeholders(pricing.cleaned_md)
    section = ProposalSection(
        section_key=section_key,
        title=title,
        content_md=pricing.cleaned_md,
        citations=raw.citations,
        placeholders=placeholders,
    )
    return section, pricing.findings


async def write_section_with_findings(
    llm: LLMClient,
    section_key: str,
    title: str,
    ctx: WriteContext,
    run_id: str,
    findings: list[AuditFinding] | None = None,
    user_instructions: str | None = None,
) -> tuple[ProposalSection, list[AuditFinding]]:
    """Like write_section, also returning the pricing-guard findings (for warnings)."""
    reqs, evidence, solution = context_pack(section_key, ctx)
    prompt = load_prompt("write_section")
    feedback = [
        {
            "type": f.type.value,
            "severity": f.severity,
            "description": f.description,
            "suggested_fix": f.suggested_fix,
        }
        for f in (findings or [])
    ]
    user = prompt.user(
        section_title=title,
        section_key=section_key,
        section_purpose=SECTION_PURPOSE.get(section_key, GENERIC_PURPOSE),
        tender_title=wrap_data("tender-title", ctx.metadata.title or "[title not stated]"),
        procuring_entity=wrap_data(
            "procuring-entity", ctx.metadata.procuring_entity or "[entity not stated]"
        ),
        glossary=wrap_data("glossary", ctx.glossary) if ctx.glossary else "none",
        audit_findings_for_section=wrap_data("revision-feedback", feedback) if feedback else "none",
        user_instructions=wrap_data("user-instructions", user_instructions)
        if user_instructions
        else "none",
        requirements_json=wrap_data("requirements", [requirement_view(r) for r in reqs]),
        evidence_json=wrap_data("evidence", [evidence_view(e) for e in evidence]),
        solution_json=wrap_data("solution", solution) if solution else to_json({}),
    )
    raw = await llm.structured(
        system=prompt.system(),
        user=user,
        schema=ProposalSection,
        model_tier="strong",
        run_id=run_id,
        node=NODE,
        prompt_version=prompt.prompt_version,
        temperature=TEMP_WRITE,
    )
    section, pricing_findings = postprocess(section_key, title, raw)
    log.info(
        "write_section.done",
        run_id=run_id,
        section_key=section_key,
        requirements=len(reqs),
        evidence=len(evidence),
        placeholders=len(section.placeholders),
        pricing_leaks=len(pricing_findings),
    )
    return section, pricing_findings


async def write_section(
    llm: LLMClient,
    section_key: str,
    title: str,
    ctx: WriteContext,
    run_id: str,
    findings: list[AuditFinding] | None = None,
    user_instructions: str | None = None,
) -> ProposalSection:
    """Context pack -> LLM -> post-process in code (placeholders, pricing guard)."""
    section, _ = await write_section_with_findings(
        llm, section_key, title, ctx, run_id, findings, user_instructions
    )
    return section


async def write_sections(
    llm: LLMClient,
    section_keys: list[str],
    ctx: WriteContext,
    run_id: str,
    findings_by_section: dict[str, list[AuditFinding]] | None = None,
    user_instructions: str | None = None,
    concurrency: int = 4,
) -> dict[str, ProposalSection]:
    """LLM sections in parallel (semaphore). Non-LLM keys (cover, toc, annexes) are skipped."""
    keys = [k for k in dict.fromkeys(section_keys) if k not in NON_LLM_SECTIONS]
    findings_by_section = findings_by_section or {}
    sections = await gather_limited(
        keys,
        lambda key: write_section(
            llm,
            key,
            section_title(key),
            ctx,
            run_id,
            findings_by_section.get(key),
            user_instructions,
        ),
        concurrency,
    )
    return dict(zip(keys, sections, strict=True))
