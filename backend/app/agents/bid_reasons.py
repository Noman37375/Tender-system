"""Optional plain-language reasons (prompt A.10). OWNER: agents agent.

LLM call: node="bid_decision", schema BidReasons, prompt "bid_reasons@1", fast tier.
BidReasons has only a `reasons` field, so a BidDecision fixture also validates as an answer.
The recommendation is decided by rules and never changed here. If the LLM call fails (other
than the run budget), the rule-derived reasons are returned instead: the reasons are optional.
"""

import structlog
from pydantic import BaseModel

from app.agents._common import TEMP_EXTRACT
from app.llm.adapter import BudgetExceededError, LLMClient
from app.prompts.loader import load_prompt, wrap_data
from app.schemas.compliance import BidDecision, ComplianceRecord, ComplianceStatus

log = structlog.get_logger(__name__)

NODE = "bid_decision"
MIN_REASONS, MAX_REASONS = 3, 7


class BidReasons(BaseModel):
    reasons: list[str]


def rule_reasons(decision: BidDecision, records: list[ComplianceRecord]) -> list[str]:
    """Deterministic reasons from the rule output only."""
    by_code = {r.req_code: r for r in records}
    out: list[str] = []
    labels = {
        "BID": "Recommendation: bid. No mandatory requirement is unmet.",
        "BID_WITH_CONDITIONS": "Recommendation: bid with conditions. Some mandatory requirements "
        "still need proof.",
        "NO_BID": "Recommendation: do not bid. At least one mandatory requirement is not met.",
    }
    out.append(labels[decision.recommendation])
    for code in decision.blocking_req_codes:
        rec = by_code.get(code)
        gap = rec.gap_description if rec and rec.gap_description else "requirement not met"
        out.append(f"{code} blocks the bid: {gap}")
    partial = [
        r for r in records if r.status in (ComplianceStatus.PARTIAL, ComplianceStatus.UNVERIFIED)
    ]
    if partial:
        out.append(
            f"{len(partial)} requirement(s) are partial or unverified and need documents: "
            + ", ".join(r.req_code for r in partial[:10])
        )
    out.append(
        "Eligibility check passed."
        if decision.eligibility_passed
        else "Eligibility check not passed."
    )
    return out[:MAX_REASONS]


async def explain(
    llm: LLMClient, decision: BidDecision, records: list[ComplianceRecord], run_id: str
) -> list[str]:
    """3-7 reasons; must not change the recommendation or add facts."""
    by_code = {r.req_code: r for r in records}
    payload = {
        "recommendation": decision.recommendation,
        "eligibility_passed": decision.eligibility_passed,
        "blocking_requirements": [
            {
                "req_code": c,
                "gap": by_code[c].gap_description if c in by_code else None,
                "action_required": by_code[c].action_required if c in by_code else None,
            }
            for c in decision.blocking_req_codes
        ],
        "partial_requirements": [
            {"req_code": r.req_code, "status": r.status.value, "gap": r.gap_description}
            for r in records
            if r.status in (ComplianceStatus.PARTIAL, ComplianceStatus.UNVERIFIED)
        ],
    }
    fallback = rule_reasons(decision, records)
    prompt = load_prompt("bid_reasons")
    try:
        result = await llm.structured(
            system=prompt.system(),
            user=prompt.user(decision_json=wrap_data("rule-engine-output", payload)),
            schema=BidReasons,
            model_tier="fast",
            run_id=run_id,
            node=NODE,
            prompt_version=prompt.prompt_version,
            temperature=TEMP_EXTRACT,
        )
    except BudgetExceededError:
        raise
    except Exception as exc:  # optional step: fall back to rule reasons
        log.warning("bid_reasons.fallback", run_id=run_id, error_type=type(exc).__name__)
        return fallback
    reasons = [r.strip() for r in result.reasons if r and r.strip()][:MAX_REASONS]
    for extra in fallback:
        if len(reasons) >= MIN_REASONS:
            break
        if extra not in reasons:
            reasons.append(extra)
    return reasons
