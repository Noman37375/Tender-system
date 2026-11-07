"""Citation checker + deterministic audit (PRD 8.3, 7.3 audit step 1). OWNER: rules agent.

1. Every cited evidence/req code must exist -> INVALID_CITATION (MAJOR).
2. Sentences carrying a factual company claim (currency amounts, years of experience, client or
   project names from evidence, certification names, "we have completed", ...) need a covering
   citation with at least one valid evidence code -> else UNSUPPORTED_CLAIM (MAJOR).
3. Certification or client names in the text that are NOT in the evidence -> UNSUPPORTED_CLAIM
   (BLOCKER). This is the "no invented facts" guard.
"""

import json
import re
from collections.abc import Iterable

from rapidfuzz import fuzz

from app.rules import pricing_guard
from app.schemas.audit import AuditFinding, FindingType
from app.schemas.evidence import EvidenceCategory, EvidenceItem
from app.schemas.proposal import DEFAULT_SECTIONS, PLACEHOLDER_PREFIX, ProposalSection
from app.schemas.tender import Requirement

PLACEHOLDER_RE = re.compile(r"\[CLIENT INPUT REQUIRED:[^\]]*\]")

# Certification families (normalised key -> regex over text).
_ISO_RE = re.compile(r"\bISO(?:\s*/\s*IEC)?[\s\-]*(\d{4,5})(?:[\-:]\d+)*\b", re.IGNORECASE)
_NAMED_CERTS: dict[str, re.Pattern[str]] = {
    "CMMI": re.compile(r"\bCMMI\b"),
    "PMP": re.compile(r"\bPMP\b"),
    "PRINCE2": re.compile(r"\bPRINCE\s?2\b", re.IGNORECASE),
    "ITIL": re.compile(r"\bITIL\b"),
    "CISSP": re.compile(r"\bCISSP\b"),
    "CISA": re.compile(r"\bCISA\b"),
    "CISM": re.compile(r"\bCISM\b"),
    "CCNA": re.compile(r"\bCCNA\b"),
    "CCNP": re.compile(r"\bCCNP\b"),
    "CCIE": re.compile(r"\bCCIE\b"),
    "TOGAF": re.compile(r"\bTOGAF\b"),
    "SOC2": re.compile(r"\bSOC\s?2\b"),
    "PCIDSS": re.compile(r"\bPCI[\s\-]?DSS\b", re.IGNORECASE),
    "CEH": re.compile(r"\bCEH\b"),
    "OSCP": re.compile(r"\bOSCP\b"),
    "COBIT": re.compile(r"\bCOBIT\b"),
    "SIXSIGMA": re.compile(r"\bSix\s+Sigma\b", re.IGNORECASE),
}

_CLAIM_PHRASES = re.compile(
    r"\b(we\s+have\s+(?:successfully\s+)?(?:completed|delivered|implemented|executed|deployed)"
    r"|our\s+team\s+includes|we\s+have\s+(?:a\s+team|over|more\s+than)"
    r"|successfully\s+(?:completed|delivered|implemented|executed)"
    r"|our\s+clients?\s+(?:include|includes|such\s+as)|we\s+are\s+certified"
    r"|certified\s+(?:to|for|under)|track\s+record|in\s+business\s+(?:for|since))\b",
    re.IGNORECASE,
)
_YEARS_EXPERIENCE = re.compile(
    r"\b\d+\+?\s*(?:years?|yrs?)\b(?:\s+of)?(?:\s+\w+){0,3}?\s*(?:experience|expertise|operation)"
    r"|\bsince\s+(?:19|20)\d{2}\b"
    r"|\b(?:established|founded|incorporated)\s+in\s+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
# A capitalised name after an experience trigger, e.g. "completed for Punjab Revenue Authority".
_CLIENT_TRIGGER = re.compile(
    r"\b(?:(?:completed|delivered|implemented|executed|deployed|undertaken|carried\s+out)"
    r"(?:\s+[\w-]+){0,6}?\s+(?:for|with|at)"
    r"|clients?\s+(?:include|includes|including|such\s+as)|worked\s+with|served"
    r"|on\s+behalf\s+of|awarded\s+by)\s+",
    re.IGNORECASE,
)
_NAME_TOKEN = r"[A-Z][\w&.'\-]*"
_NAME_AT = re.compile(rf"(?:[Tt]he\s+)?({_NAME_TOKEN}(?:\s+(?:of|and|&|for|the|{_NAME_TOKEN}))*)")
# A certification mention is a company claim only in a "holding" context; "aligned with ISO
# 27001" describes a standard, "we are ISO 27001 certified" claims a certificate.
_CERT_CLAIM_CONTEXT = re.compile(
    r"\b(certified|certification|certifications|certificate|accredited|accreditation|holds?"
    r"|holding|achieved|awarded|qualified|appraised|assessed\s+at|rated)\b",
    re.IGNORECASE,
)
_GENERIC_NAMES = {
    "the",
    "a",
    "an",
    "our",
    "various",
    "several",
    "multiple",
    "many",
    "government",
    "public",
    "private",
    "clients",
    "client",
    "customers",
    "organisations",
    "organizations",
}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[*_(\"'])")


def extract_placeholders(content_md: str) -> list[str]:
    """Every [CLIENT INPUT REQUIRED: ...] marker, in order."""
    return PLACEHOLDER_RE.findall(content_md)


# ---------------------------------------------------------------- evidence vocabulary


def _evidence_text(item: EvidenceItem) -> str:
    return f"{item.description} {json.dumps(item.attributes, default=str)}"


def _claimed_cert_keys(sentence: str) -> set[str]:
    return _cert_keys(sentence) if _CERT_CLAIM_CONTEXT.search(sentence) else set()


def _cert_keys(text: str) -> set[str]:
    keys = {f"ISO{m.group(1)}" for m in _ISO_RE.finditer(text)}
    keys.update(key for key, rx in _NAMED_CERTS.items() if rx.search(text))
    return keys


def _client_names(evidence: Iterable[EvidenceItem]) -> list[str]:
    names: list[str] = []
    for item in evidence:
        for key in ("client", "title", "issuer", "name", "partner"):
            value = item.attributes.get(key)
            if isinstance(value, str) and value.strip():
                names.append(value.strip())
    return names


def _name_known(candidate: str, known_names: list[str], corpus: str) -> bool:
    cand = candidate.lower().strip(" .,;:")
    if not cand:
        return True
    if cand in corpus:
        return True
    return any(fuzz.token_set_ratio(cand, n.lower()) >= 85 for n in known_names)


def _clean_candidate(raw: str) -> str:
    words = raw.strip(" .,;:").split()
    while words and words[-1].lower() in {"of", "and", "&", "for", "the"}:
        words.pop()
    if words and words[0].lower() == "the":
        words = words[1:]
    return " ".join(words)


# ---------------------------------------------------------------- sentences & claims


def _sentences(content_md: str) -> list[str]:
    out: list[str] = []
    for raw_line in content_md.splitlines():
        line = raw_line.strip()
        if not line or re.fullmatch(r"\|?[\s:\-|]+\|?", line):
            continue
        line = re.sub(r"^(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)", "", line)
        line = line.replace("**", "").replace("__", "")
        cells = [c.strip() for c in line.strip("|").split("|")] if line.startswith("|") else [line]
        for cell in cells:
            out.extend(s.strip() for s in _SENTENCE_SPLIT.split(cell) if s.strip())
    return out


def _is_claim(sentence: str, known_names: list[str]) -> bool:
    if pricing_guard.CURRENCY_AMOUNT_RE.search(sentence):
        return True
    if _YEARS_EXPERIENCE.search(sentence) or _CLAIM_PHRASES.search(sentence):
        return True
    if _claimed_cert_keys(sentence):
        return True
    low = sentence.lower()
    return any(len(n) >= 4 and n.lower() in low for n in known_names)


def _covered(sentence: str, section: ProposalSection, valid_codes: set[str]) -> bool:
    low = sentence.lower()
    for cit in section.citations:
        if not any(code in valid_codes for code in cit.evidence_codes):
            continue
        claim = cit.claim.strip().lower()
        if not claim:
            continue
        if claim in low or low in claim or fuzz.partial_ratio(claim, low) >= 80:
            return True
    return False


def _invented_names(
    sentence: str,
    evidence_certs: set[str],
    known_names: list[str],
    corpus: str,
    allowed_names: list[str],
) -> list[str]:
    invented = [
        f"certification {key}" for key in sorted(_claimed_cert_keys(sentence) - evidence_certs)
    ]
    for trig in _CLIENT_TRIGGER.finditer(sentence):
        m = _NAME_AT.match(sentence, trig.end())
        if m is None:
            continue
        candidate = _clean_candidate(m.group(1))
        if not candidate or candidate.lower() in _GENERIC_NAMES:
            continue
        if _name_known(candidate, known_names + allowed_names, corpus):
            continue
        invented.append(f"client '{candidate}'")
    return invented


def check_section(
    section: ProposalSection,
    evidence_by_code: dict[str, EvidenceItem],
    req_codes: set[str],
    *,
    allowed_names: Iterable[str] = (),  # e.g. procuring entity / tender title: not company claims
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    key = section.section_key

    # 1. citations must point at existing codes
    for cit in section.citations:
        for code in cit.evidence_codes:
            if code not in evidence_by_code:
                findings.append(
                    AuditFinding(
                        type=FindingType.INVALID_CITATION,
                        severity="MAJOR",
                        section_key=key,
                        description=f"Citation references unknown evidence code {code}",
                        suggested_fix="Cite an existing evidence code or remove the claim.",
                    )
                )
        for code in cit.req_codes:
            if code not in req_codes:
                findings.append(
                    AuditFinding(
                        type=FindingType.INVALID_CITATION,
                        severity="MAJOR",
                        section_key=key,
                        description=f"Citation references unknown requirement code {code}",
                        suggested_fix="Cite an existing requirement code.",
                    )
                )

    evidence = list(evidence_by_code.values())
    corpus = " ".join(_evidence_text(i) for i in evidence).lower()
    evidence_certs = _cert_keys(" ".join(_evidence_text(i) for i in evidence))
    name_categories = (EvidenceCategory.PROJECT, EvidenceCategory.PARTNERSHIP)
    known_names = _client_names(i for i in evidence if i.category in name_categories)
    allowed = [a for a in allowed_names if a]
    valid_codes = set(evidence_by_code)

    text = PLACEHOLDER_RE.sub(" ", section.content_md)
    for sentence in _sentences(text):
        invented = _invented_names(sentence, evidence_certs, known_names, corpus, allowed)
        if invented:
            findings.append(
                AuditFinding(
                    type=FindingType.UNSUPPORTED_CLAIM,
                    severity="BLOCKER",
                    section_key=key,
                    description=(
                        f'Not found in company evidence: {", ".join(invented)} — "{sentence[:200]}"'
                    ),
                    suggested_fix=(
                        "Remove the claim or replace it with "
                        f"{PLACEHOLDER_PREFIX} evidence of ...]."
                    ),
                )
            )
            continue
        if _is_claim(sentence, known_names) and not _covered(sentence, section, valid_codes):
            findings.append(
                AuditFinding(
                    type=FindingType.UNSUPPORTED_CLAIM,
                    severity="MAJOR",
                    section_key=key,
                    description=(
                        f'Company claim without a supporting citation: "{sentence[:200]}"'
                    ),
                    suggested_fix="Add a citation with the supporting evidence code, or remove it.",
                )
            )
    return findings


_LLM_SECTION = {k: by_llm for k, _, by_llm in DEFAULT_SECTIONS}


def deterministic_audit(
    sections: dict[str, ProposalSection],
    evidence_by_code: dict[str, EvidenceItem],
    requirements: list[Requirement],
    required_section_keys: list[str],
    compliance_annex_req_codes: set[str],
) -> list[AuditFinding]:
    """Citations, mandatory coverage, required sections present, pricing guard."""
    findings: list[AuditFinding] = []
    req_codes = {r.req_code for r in requirements}

    for key, section in sections.items():
        findings.extend(check_section(section, evidence_by_code, req_codes))
        findings.extend(pricing_guard.scan(key, section.content_md).findings)

    cited_reqs = {code for s in sections.values() for c in s.citations for code in c.req_codes}
    covered = cited_reqs | compliance_annex_req_codes
    for req in requirements:
        if req.is_mandatory and req.req_code not in covered:
            findings.append(
                AuditFinding(
                    type=FindingType.MISSING_MANDATORY_COVERAGE,
                    severity="MAJOR",
                    section_key=None,
                    description=(
                        f"Mandatory requirement {req.req_code} is not addressed in any section "
                        "or the compliance annex"
                    ),
                    suggested_fix=f"Address {req.req_code} and cite it in the relevant section.",
                )
            )

    for key in required_section_keys:
        present = sections.get(key)
        missing = present is None or (
            _LLM_SECTION.get(key, True) and not present.content_md.strip()
        )
        if missing:
            findings.append(
                AuditFinding(
                    type=FindingType.MISSING_SECTION,
                    severity="MAJOR",
                    section_key=key,
                    description=f"Required section '{key}' is missing or empty",
                    suggested_fix=f"Generate the '{key}' section.",
                )
            )
    return findings
