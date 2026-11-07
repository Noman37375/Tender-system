from pydantic import BaseModel

PLACEHOLDER_PREFIX = "[CLIENT INPUT REQUIRED:"


class Citation(BaseModel):
    claim: str
    evidence_codes: list[str] = []
    req_codes: list[str] = []


class ProposalSection(BaseModel):
    section_key: str
    title: str
    content_md: str
    citations: list[Citation]
    placeholders: list[str]  # every [CLIENT INPUT REQUIRED: ...] in content_md


# PRD 7.4 default section list: (key, title, written_by_llm)
DEFAULT_SECTIONS: list[tuple[str, str, bool]] = [
    ("cover", "Cover Page", False),
    ("toc", "Table of Contents", False),
    ("executive_summary", "Executive Summary", True),
    ("understanding", "Understanding of Requirements", True),
    ("company_profile", "Company Profile", True),
    ("technical_solution", "Proposed Technical Solution", True),
    ("architecture", "Solution Architecture", True),
    ("scope_of_work", "Scope of Work", True),
    ("methodology", "Implementation Methodology", True),
    ("timeline", "Project Timeline", True),
    ("team", "Team Composition", True),
    ("experience", "Relevant Project Experience", True),
    ("testing_qa", "Testing and Quality Assurance", True),
    ("deployment", "Deployment and Commissioning", True),
    ("support", "Support and Maintenance", True),
    ("assumptions", "Assumptions and Dependencies", True),
    ("compliance_annex", "Annex A — Compliance Matrix", False),
    ("forms_annex", "Annex B — Prescribed Forms", False),
]
