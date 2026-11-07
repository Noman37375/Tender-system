"""solution_design (PRD 7.3, prompt A.6). OWNER: agents agent.

LLM calls: node="solution_design", schema SolutionDesign, strong tier.
1. prompt "solution_design@1".
2. Only if mandatory TECHNICAL req_codes are missing from requirement_traceability: one
   re-prompt, prompt "solution_design_retrace@1". Codes still missing afterwards are appended
   to capability_gaps (AC-10).
"""

import structlog

from app.agents._common import TEMP_DESIGN, evidence_view, requirement_view
from app.llm.adapter import LLMClient
from app.prompts.loader import load_prompt, wrap_data
from app.schemas.evidence import EvidenceCategory, EvidenceItem
from app.schemas.solution import SolutionDesign
from app.schemas.tender import ReqCategory, Requirement

log = structlog.get_logger(__name__)

NODE = "solution_design"
INPUT_REQ_CATEGORIES = {ReqCategory.TECHNICAL, ReqCategory.DELIVERABLE, ReqCategory.EVALUATION}
INPUT_EVIDENCE_CATEGORIES = {
    EvidenceCategory.CAPABILITY,
    EvidenceCategory.PROJECT,
    EvidenceCategory.PERSONNEL,
}


def missing_traceability(design: SolutionDesign, requirements: list[Requirement]) -> list[str]:
    traced = {code for code, how in design.requirement_traceability.items() if how and how.strip()}
    return [
        r.req_code
        for r in requirements
        if r.category == ReqCategory.TECHNICAL and r.is_mandatory and r.req_code not in traced
    ]


def gap_text(req: Requirement) -> str:
    return f"{req.req_code}: not addressed by the solution design — {req.description}"


async def design_solution(
    llm: LLMClient,
    requirements: list[Requirement],
    evidence: list[EvidenceItem],
    scope_summary: str,
    run_id: str,
) -> SolutionDesign:
    """Every mandatory TECHNICAL req_code traced; re-prompt once, then add to capability_gaps."""
    reqs = [r for r in requirements if r.category in INPUT_REQ_CATEGORIES]
    items = [e for e in evidence if e.category in INPUT_EVIDENCE_CATEGORIES]
    prompt = load_prompt("solution_design")
    system = prompt.system()
    user = prompt.user(
        scope_summary=wrap_data("scope-summary", scope_summary),
        requirements_json=wrap_data("requirements", [requirement_view(r) for r in reqs]),
        evidence_json=wrap_data("evidence", [evidence_view(e) for e in items]),
    )
    design = await llm.structured(
        system=system,
        user=user,
        schema=SolutionDesign,
        model_tier="strong",
        run_id=run_id,
        node=NODE,
        prompt_version=prompt.prompt_version,
        temperature=TEMP_DESIGN,
    )
    missing = missing_traceability(design, reqs)
    if missing:
        retrace = load_prompt("solution_design_retrace")
        by_code = {r.req_code: r for r in reqs}
        retry_user = retrace.user(
            original_user=user,
            missing_json=wrap_data(
                "missing-requirements", [requirement_view(by_code[c]) for c in missing]
            ),
            previous_json=wrap_data("previous-design", design.model_dump(mode="json")),
        )
        design = await llm.structured(
            system=system,
            user=retry_user,
            schema=SolutionDesign,
            model_tier="strong",
            run_id=run_id,
            node=NODE,
            prompt_version=retrace.prompt_version,
            temperature=TEMP_DESIGN,
        )
        still_missing = missing_traceability(design, reqs)
        if still_missing:
            gaps = list(design.capability_gaps)
            for code in still_missing:
                text = gap_text(by_code[code])
                if not any(g.startswith(f"{code}:") for g in gaps):
                    gaps.append(text)
            design = design.model_copy(update={"capability_gaps": gaps})
        log.info(
            "solution_design.retrace",
            run_id=run_id,
            missing_first=len(missing),
            missing_after=len(still_missing),
        )
    # Drop traceability entries for codes that are not requirements (they would become
    # invalid citations downstream).
    known = {r.req_code for r in requirements}
    trace = {k: v for k, v in design.requirement_traceability.items() if k in known}
    return design.model_copy(update={"requirement_traceability": trace})
