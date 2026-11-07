from app.rules.citation_checker import check_section, deterministic_audit, extract_placeholders
from app.rules.pricing_guard import PRICING_PLACEHOLDER
from app.schemas.audit import AuditFinding, FindingType
from app.schemas.evidence import EvidenceCategory, EvidenceItem
from app.schemas.proposal import Citation, ProposalSection
from app.schemas.tender import ReqCategory

from .factories import ev, project, req


def evidence() -> dict[str, EvidenceItem]:
    items = [
        ev(
            "EV-CER-001",
            description="ISO/IEC 27001:2013 certificate",
            name="ISO 27001",
            issuer="SGS",
            expiry_date="2030-01-01",
        ),
        project("EV-PRJ-001", client="Punjab Revenue Authority"),
        ev(
            "EV-PER-001",
            EvidenceCategory.PERSONNEL,
            name="Ali Khan",
            role="Project Manager",
            years_experience=12,
            certifications=["PMP"],
        ),
    ]
    return {i.evidence_code: i for i in items}


def section(content: str, citations: list[Citation] | None = None, key: str = "experience") -> ProposalSection:
    return ProposalSection(
        section_key=key,
        title="Relevant Project Experience",
        content_md=content,
        citations=citations or [],
        placeholders=extract_placeholders(content),
    )


def kinds(findings: list[AuditFinding]) -> list[tuple[FindingType, str]]:
    return [(f.type, f.severity) for f in findings]


def test_extract_placeholders_in_order() -> None:
    md = "A [CLIENT INPUT REQUIRED: bank name] and\n[CLIENT INPUT REQUIRED: signatory]."
    assert extract_placeholders(md) == [
        "[CLIENT INPUT REQUIRED: bank name]",
        "[CLIENT INPUT REQUIRED: signatory]",
    ]
    assert extract_placeholders("nothing") == []


def test_invalid_citation_codes_are_major() -> None:
    s = section("Plain text.", [Citation(claim="x", evidence_codes=["EV-X-1"], req_codes=["ELG-9"])])
    findings = check_section(s, evidence(), {"ELG-001"})
    assert kinds(findings) == [
        (FindingType.INVALID_CITATION, "MAJOR"),
        (FindingType.INVALID_CITATION, "MAJOR"),
    ]


def test_supported_claims_pass() -> None:
    md = (
        "We have completed an ERP implementation for Punjab Revenue Authority.\n\n"
        "- Our team includes a PMP-certified project manager with 12 years of experience.\n"
        "We are ISO 27001 certified."
    )
    cites = [
        Citation(claim="completed an ERP implementation for Punjab Revenue Authority",
                 evidence_codes=["EV-PRJ-001"]),
        Citation(claim="Our team includes a PMP-certified project manager", evidence_codes=["EV-PER-001"]),
        Citation(claim="We are ISO 27001 certified", evidence_codes=["EV-CER-001"]),
    ]
    assert check_section(section(md, cites), evidence(), set()) == []


def test_uncited_claim_is_major() -> None:
    md = "We have completed more than 40 projects nationwide."
    findings = check_section(section(md), evidence(), set())
    assert kinds(findings) == [(FindingType.UNSUPPORTED_CLAIM, "MAJOR")]


def test_citation_with_only_invalid_or_req_codes_does_not_cover() -> None:
    md = "We have completed an ERP implementation for Punjab Revenue Authority."
    cites = [Citation(claim=md, evidence_codes=["EV-GHOST"], req_codes=["EXP-001"])]
    findings = check_section(section(md, cites), evidence(), {"EXP-001"})
    assert (FindingType.UNSUPPORTED_CLAIM, "MAJOR") in kinds(findings)


def test_years_and_currency_claims_detected() -> None:
    for md in [
        "The firm has 15 years of experience in e-governance.",
        "Established in 2005, the firm operates nationwide.",
        "The firm's turnover reached PKR 900 million.",
    ]:
        assert kinds(check_section(section(md, key="company_profile"), evidence(), set())) == [
            (FindingType.UNSUPPORTED_CLAIM, "MAJOR")
        ], md


def test_known_client_name_mention_is_a_claim() -> None:
    md = "Punjab Revenue Authority appreciated the delivery."
    assert kinds(check_section(section(md), evidence(), set())) == [
        (FindingType.UNSUPPORTED_CLAIM, "MAJOR")
    ]


def test_fake_certification_is_blocker() -> None:
    md = "Our company is CMMI Level 5 certified and holds ISO 9001 certification."
    cites = [Citation(claim=md, evidence_codes=["EV-CER-001"])]  # citing something unrelated
    findings = check_section(section(md, cites, key="executive_summary"), evidence(), set())
    assert kinds(findings) == [(FindingType.UNSUPPORTED_CLAIM, "BLOCKER")]
    assert "CMMI" in findings[0].description and "ISO9001" in findings[0].description


def test_standard_reference_is_not_a_certification_claim() -> None:
    md = "The security design aligns with ISO 22301 and ITIL practices."
    assert check_section(section(md, key="technical_solution"), evidence(), set()) == []


def test_invented_client_is_blocker() -> None:
    md = "We have successfully delivered a similar system for Sindh Police Department."
    cites = [Citation(claim=md, evidence_codes=["EV-PRJ-001"])]
    findings = check_section(section(md, cites), evidence(), set())
    assert kinds(findings) == [(FindingType.UNSUPPORTED_CLAIM, "BLOCKER")]
    assert "Sindh Police Department" in findings[0].description


def test_allowed_names_and_generic_words_are_not_clients() -> None:
    md = "We have delivered solutions for the Federal Board of Revenue."
    s = section(md, [Citation(claim=md, evidence_codes=["EV-PRJ-001"])])
    assert kinds(check_section(s, evidence(), set())) == [(FindingType.UNSUPPORTED_CLAIM, "BLOCKER")]
    assert check_section(s, evidence(), set(), allowed_names=["Federal Board of Revenue"]) == []
    generic = "We have delivered systems for various clients."
    s2 = section(generic, [Citation(claim=generic, evidence_codes=["EV-PRJ-001"])])
    assert check_section(s2, evidence(), set()) == []


def test_placeholders_are_ignored_and_tables_parsed() -> None:
    md = (
        "[CLIENT INPUT REQUIRED: ISO 9001 certificate if held]\n\n"
        "| Project | Client |\n|---|---|\n| ERP | Punjab Revenue Authority |\n"
    )
    findings = check_section(section(md), evidence(), set())
    assert kinds(findings) == [(FindingType.UNSUPPORTED_CLAIM, "MAJOR")]  # table cell uncited


def test_deterministic_audit_combines_checks() -> None:
    reqs = [
        req("ELG-001"),
        req("TEC-001", ReqCategory.TECHNICAL),
        req("TEC-002", ReqCategory.TECHNICAL),
        req("TEC-003", ReqCategory.TECHNICAL, mandatory=False),
    ]
    sections = {
        "technical_solution": ProposalSection(
            section_key="technical_solution",
            title="Proposed Technical Solution",
            content_md="We use microservices. The license cost is USD 20,000.",
            citations=[Citation(claim="microservices", req_codes=["TEC-001"])],
            placeholders=[],
        ),
        "compliance_annex": ProposalSection(
            section_key="compliance_annex", title="Annex A", content_md="", citations=[], placeholders=[]
        ),
        "timeline": ProposalSection(
            section_key="timeline", title="Timeline", content_md="  ", citations=[], placeholders=[]
        ),
    }
    findings = deterministic_audit(
        sections,
        evidence(),
        reqs,
        ["technical_solution", "compliance_annex", "timeline", "team"],
        {"ELG-001"},
    )
    got = kinds(findings)
    assert (FindingType.PRICING_LEAK, "BLOCKER") in got
    missing_cov = [f for f in findings if f.type == FindingType.MISSING_MANDATORY_COVERAGE]
    assert [f.description.split()[2] for f in missing_cov] == ["TEC-002"]
    missing_sections = {f.section_key for f in findings if f.type == FindingType.MISSING_SECTION}
    assert missing_sections == {"timeline", "team"}  # annex may be empty (builder renders it)
    assert PRICING_PLACEHOLDER not in sections["technical_solution"].content_md  # no mutation
