"""Compliance matching (PRD 7.3 compliance steps 1-2, prompt A.5). OWNER: agents agent.

select_candidates: one llm.embed call over all requirement + evidence descriptions; per
requirement, evidence in the mapped categories comes first (by cosine similarity), remaining
slots up to k are filled with the most similar other evidence.

match_requirements: node="compliance", schema LLMMatchBatch, prompt "compliance_match@1", fast
tier, 10 requirements per call, batches run concurrently. Requirements with no candidate
evidence are not sent (nothing to judge) and get an UNVERIFIED match directly; so do
requirements the model skipped. Output: exactly one LLMMatch per requirement, input order.
Evidence codes are passed through as cited; rule R1 (rules engine) drops invalid ones.
"""

import math

import structlog

from app.agents._common import (
    TEMP_EXTRACT,
    evidence_view,
    gather_limited,
    llm_concurrency,
    requirement_view,
)
from app.llm.adapter import LLMClient
from app.prompts.loader import load_prompt, wrap_data
from app.schemas.common import Confidence
from app.schemas.compliance import ComplianceStatus, LLMMatch, LLMMatchBatch
from app.schemas.evidence import EvidenceCategory, EvidenceItem
from app.schemas.tender import ReqCategory, Requirement

log = structlog.get_logger(__name__)

NODE = "compliance"
BATCH_SIZE = 10

E = EvidenceCategory
CATEGORY_MAP: dict[ReqCategory, set[EvidenceCategory]] = {
    ReqCategory.ELIGIBILITY: {E.COMPANY_REGISTRATION, E.TAX_REGISTRATION, E.CERTIFICATION, E.OTHER},
    ReqCategory.FINANCIAL: {E.FINANCIAL},
    ReqCategory.EXPERIENCE: {E.PROJECT},
    ReqCategory.PERSONNEL: {E.PERSONNEL},
    ReqCategory.CERTIFICATION: {E.CERTIFICATION},
    ReqCategory.TECHNICAL: {E.CAPABILITY, E.PROJECT, E.PARTNERSHIP, E.CERTIFICATION, E.PERSONNEL},
    ReqCategory.SUBMISSION: {E.COMPANY_REGISTRATION, E.TAX_REGISTRATION, E.OTHER},
    ReqCategory.DELIVERABLE: {E.CAPABILITY, E.PROJECT},
    ReqCategory.EVALUATION: set(EvidenceCategory),
    ReqCategory.COMMERCIAL: {E.FINANCIAL, E.OTHER},
}


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _embed_text_req(req: Requirement) -> str:
    return f"{req.category.value}: {req.description}"


def _embed_text_ev(item: EvidenceItem) -> str:
    return f"{item.category.value}: {item.description}"


async def select_candidates(
    llm: LLMClient, requirements: list[Requirement], evidence: list[EvidenceItem], k: int = 8
) -> dict[str, list[EvidenceItem]]:
    """Top-k evidence per req_code: category filter + embedding cosine similarity."""
    if not requirements:
        return {}
    if not evidence or k <= 0:
        return {r.req_code: [] for r in requirements}
    vectors = await llm.embed(
        [_embed_text_req(r) for r in requirements] + [_embed_text_ev(e) for e in evidence]
    )
    req_vecs, ev_vecs = vectors[: len(requirements)], vectors[len(requirements) :]
    out: dict[str, list[EvidenceItem]] = {}
    for req, rvec in zip(requirements, req_vecs, strict=True):
        allowed = CATEGORY_MAP.get(req.category, set())
        scored = [
            (item.category in allowed, cosine(rvec, evec), idx)
            for idx, (item, evec) in enumerate(zip(evidence, ev_vecs, strict=True))
        ]
        # In-category first, then by similarity; index keeps ties deterministic.
        scored.sort(key=lambda t: (not t[0], -t[1], t[2]))
        out[req.req_code] = [evidence[idx] for _, _, idx in scored[:k]]
    return out


def unverified_match(req: Requirement, reason: str) -> LLMMatch:
    return LLMMatch(
        req_code=req.req_code,
        proposed_status=ComplianceStatus.UNVERIFIED,
        confidence=Confidence.LOW,
        evidence_codes=[],
        relevant_evidence_codes=[],
        rationale=reason,
        gap_description="No evidence was matched to this requirement.",
        action_required="Provide documentary evidence that satisfies this requirement.",
    )


async def _match_batch(
    llm: LLMClient,
    batch: list[Requirement],
    candidates: dict[str, list[EvidenceItem]],
    run_id: str,
) -> list[LLMMatch]:
    prompt = load_prompt("compliance_match")
    payload = [
        {
            **requirement_view(req),
            "candidate_evidence": [evidence_view(e) for e in candidates.get(req.req_code, [])],
        }
        for req in batch
    ]
    result = await llm.structured(
        system=prompt.system(),
        user=prompt.user(batch_json=wrap_data("compliance-batch", payload)),
        schema=LLMMatchBatch,
        model_tier="fast",
        run_id=run_id,
        node=NODE,
        prompt_version=prompt.prompt_version,
        temperature=TEMP_EXTRACT,
    )
    return result.matches


async def match_requirements(
    llm: LLMClient,
    candidates: dict[str, list[EvidenceItem]],
    requirements: list[Requirement],
    run_id: str,
) -> list[LLMMatch]:
    """Batches of 10 per call. Exactly one LLMMatch per requirement (UNVERIFIED if skipped)."""
    to_send = [r for r in requirements if candidates.get(r.req_code)]
    batches = [to_send[i : i + BATCH_SIZE] for i in range(0, len(to_send), BATCH_SIZE)]
    results = await gather_limited(
        batches, lambda b: _match_batch(llm, b, candidates, run_id), llm_concurrency()
    )
    sent_codes = {r.req_code for r in to_send}
    by_code: dict[str, LLMMatch] = {}
    for batch, matches in zip(batches, results, strict=True):
        batch_codes = {r.req_code for r in batch}
        for match in matches:
            if match.req_code in batch_codes and match.req_code not in by_code:
                by_code[match.req_code] = match

    out: list[LLMMatch] = []
    skipped = 0
    for req in requirements:
        if req.req_code in by_code:
            out.append(by_code[req.req_code])
        elif req.req_code in sent_codes:
            skipped += 1
            out.append(unverified_match(req, "The model returned no assessment for this item."))
        else:
            out.append(unverified_match(req, "No candidate evidence was found for this item."))
    log.info(
        "compliance.matched",
        run_id=run_id,
        requirements=len(requirements),
        llm_batches=len(batches),
        skipped_by_model=skipped,
    )
    return out
