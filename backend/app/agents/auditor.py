"""audit LLM review (PRD 7.3 audit steps 2-3, prompt A.9). OWNER: agents agent.

LLM calls: node="audit", schema AuditFindingList, prompt "audit_review@1", strong tier.
Sections are batched by size (~40k characters of section content per call), so a small
proposal is one call. `review` returns only the NEW findings from the LLM; the graph passes
deterministic + LLM findings to `build_report`.

Code filtering of LLM findings: only the types the prompt allows (deterministic-only types
INVALID_CITATION and MISSING_SECTION are dropped), section_key must be in the batch (or None),
and findings that repeat an automated one (same type + section, similar text) are dropped.
"""

import structlog
from rapidfuzz import fuzz

from app.agents._common import TEMP_EXTRACT, evidence_view, gather_limited, llm_concurrency
from app.llm.adapter import LLMClient
from app.prompts.loader import load_prompt, wrap_data
from app.schemas.audit import AuditFinding, AuditFindingList, AuditReport, FindingType
from app.schemas.evidence import EvidenceItem
from app.schemas.proposal import ProposalSection
from app.schemas.tender import Requirement

log = structlog.get_logger(__name__)

NODE = "audit"
BATCH_CHARS = 40_000
DUPLICATE_SIMILARITY = 85
LLM_FINDING_TYPES = {
    FindingType.UNSUPPORTED_CLAIM,
    FindingType.CONTRADICTION,
    FindingType.MISSING_MANDATORY_COVERAGE,
    FindingType.STRUCTURE_DEVIATION,
    FindingType.TERMINOLOGY_INCONSISTENCY,
    FindingType.PRICING_LEAK,
}
FAILING_SEVERITIES = {"BLOCKER", "MAJOR"}


def batch_sections(
    sections: dict[str, ProposalSection], max_chars: int = BATCH_CHARS
) -> list[list[ProposalSection]]:
    batches: list[list[ProposalSection]] = []
    current: list[ProposalSection] = []
    used = 0
    for section in sections.values():
        size = len(section.content_md)
        if current and used + size > max_chars:
            batches.append(current)
            current, used = [], 0
        current.append(section)
        used += size
    if current:
        batches.append(current)
    return batches


def _is_duplicate(finding: AuditFinding, automated: list[AuditFinding]) -> bool:
    for auto in automated:
        if auto.type == finding.type and auto.section_key == finding.section_key:
            if fuzz.token_set_ratio(auto.description, finding.description) >= DUPLICATE_SIMILARITY:
                return True
    return False


def filter_findings(
    findings: list[AuditFinding], batch_keys: set[str], automated: list[AuditFinding]
) -> list[AuditFinding]:
    out: list[AuditFinding] = []
    for finding in findings:
        if finding.type not in LLM_FINDING_TYPES:
            continue
        if finding.section_key is not None and finding.section_key not in batch_keys:
            continue
        if _is_duplicate(finding, automated):
            continue
        out.append(finding)
    return out


async def _review_batch(
    llm: LLMClient,
    batch: list[ProposalSection],
    requirements: list[Requirement],
    evidence: list[EvidenceItem],
    automated: list[AuditFinding],
    run_id: str,
) -> list[AuditFinding]:
    prompt = load_prompt("audit_review")
    keys = {s.section_key for s in batch}
    user = prompt.user(
        sections_json=wrap_data("proposal-sections", [s.model_dump(mode="json") for s in batch]),
        requirements_json=wrap_data(
            "requirements",
            [
                {
                    "req_code": r.req_code,
                    "category": r.category.value,
                    "is_mandatory": r.is_mandatory,
                    "description": r.description,
                }
                for r in requirements
            ],
        ),
        evidence_json=wrap_data("evidence-register", [evidence_view(e) for e in evidence]),
        automated_json=wrap_data(
            "automated-findings",
            [
                f.model_dump(mode="json")
                for f in automated
                if f.section_key in keys or f.section_key is None
            ],
        ),
    )
    result = await llm.structured(
        system=prompt.system(),
        user=user,
        schema=AuditFindingList,
        model_tier="strong",
        run_id=run_id,
        node=NODE,
        prompt_version=prompt.prompt_version,
        temperature=TEMP_EXTRACT,
    )
    return filter_findings(result.findings, keys, automated)


async def review(
    llm: LLMClient,
    sections: dict[str, ProposalSection],
    requirements: list[Requirement],
    evidence: list[EvidenceItem],
    automated_findings: list[AuditFinding],
    run_id: str,
) -> list[AuditFinding]:
    batches = batch_sections(sections)
    if not batches:
        return []
    results = await gather_limited(
        batches,
        lambda b: _review_batch(llm, b, requirements, evidence, automated_findings, run_id),
        llm_concurrency(),
    )
    findings = [f for batch in results for f in batch]
    log.info("audit.review", run_id=run_id, batches=len(batches), findings=len(findings))
    return findings


def build_report(findings: list[AuditFinding]) -> AuditReport:
    """passed = no BLOCKER and no MAJOR; sections_to_revise = sections with BLOCKER/MAJOR."""
    failing = [f for f in findings if f.severity in FAILING_SEVERITIES]
    to_revise = list(dict.fromkeys(f.section_key for f in failing if f.section_key))
    return AuditReport(passed=not failing, findings=list(findings), sections_to_revise=to_revise)
