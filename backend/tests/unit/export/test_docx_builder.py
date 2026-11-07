from io import BytesIO

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_COLOR_INDEX
from docx.oxml.ns import qn
from docx.shared import Cm, Mm

from app.export.docx_builder import WATERMARK_TEXT, build_proposal_docx
from app.export.markdown_docx import has_highlighted_placeholder
from app.schemas.common import SourceRef
from app.schemas.compliance import ComplianceStatus as S
from app.schemas.forms import FormField, TenderForm
from app.schemas.proposal import Citation, ProposalSection
from app.schemas.tender import TenderMetadata

from ..rules.factories import record, req

META = TenderMetadata(
    title="Supply of ERP System",
    reference_no="PRA/IT/2026/07",
    procuring_entity="Punjab Revenue Authority",
    scope_summary="ERP",
    sources=[SourceRef(document_id="d", page=1, quote="q")],
)

MD = """# Technical Solution

Intro paragraph with **bold text**, *italic text*, ***both***, `code` and
a continued line.

## Components

- First bullet
- Second bullet with [CLIENT INPUT REQUIRED: server count]
  - Nested bullet

1. Step one
2. Step two

Between lists.

1. Again one
2. Again two

| Component | Technology |
|---|---|
| API | FastAPI |
| DB | PostgreSQL |

> A quoted note

---

```
code block line
```
"""


def sections() -> list[ProposalSection]:
    return [
        ProposalSection(section_key="cover", title="Cover Page", content_md="", citations=[],
                        placeholders=[]),
        ProposalSection(
            section_key="technical_solution",
            title="Technical Solution",
            content_md=MD,
            citations=[Citation(claim="Uses FastAPI", evidence_codes=["EV-CAP-001"],
                                req_codes=["TEC-001"])],
            placeholders=["[CLIENT INPUT REQUIRED: server count]"],
        ),
        ProposalSection(section_key="team", title="Team Composition",
                        content_md="Plain team text.", citations=[], placeholders=[]),
        ProposalSection(section_key="compliance_annex", title="Annex A — Compliance Matrix",
                        content_md="SHOULD NOT RENDER", citations=[], placeholders=[]),
    ]


FORMS = [
    TenderForm(
        form_code="F-1",
        title="Bid Submission Form",
        source_page=12,
        envelope="TECHNICAL",
        fields=[
            FormField(label="Bidder name", value="Acme Ltd", status="FILLED",
                      evidence_codes=["EV-REG-001"]),
            FormField(label="Signature", status="NEEDS_INPUT"),
            FormField(label="JV partner", status="NOT_APPLICABLE"),
        ],
    ),
    TenderForm(
        form_code="F-9",
        title="Price Schedule",
        source_page=30,
        envelope="FINANCIAL",
        fields=[FormField(label="Total price", value="PKR 1,000,000", status="FILLED")],
    ),
]


def build(draft: bool = True, include_citations: bool = False) -> DocxDocument:
    data = build_proposal_docx(
        META,
        "Acme Ltd",
        sections(),
        [req("ELG-001"), req("TEC-001", mandatory=False, description="Use open source")],
        [record("ELG-001", S.COMPLIANT, codes=["EV-CER-001"]), record("TEC-001", S.PARTIAL)],
        FORMS,
        draft=draft,
        include_citations=include_citations,
    )
    assert data[:2] == b"PK"
    return Document(BytesIO(data))


def all_text(doc: DocxDocument) -> str:
    parts = [p.text for p in doc.paragraphs]
    for t in doc.tables:
        for row in t.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def test_page_setup_header_footer() -> None:
    doc = build()
    sec = doc.sections[0]
    assert sec.page_width == Mm(210) and sec.page_height == Mm(297)
    assert sec.left_margin == Cm(2.5) and sec.top_margin == Cm(2.5)
    assert "PRA/IT/2026/07" in sec.header.paragraphs[0].text
    footer_xml = sec.footer._element.xml
    assert "Confidential" in footer_xml
    assert "PAGE" in footer_xml and "NUMPAGES" in footer_xml


def test_watermark_only_on_draft() -> None:
    assert WATERMARK_TEXT in build(draft=True).sections[0].header._element.xml
    assert WATERMARK_TEXT not in build(draft=False).sections[0].header._element.xml


def test_cover_and_toc() -> None:
    doc = build()
    text = all_text(doc)
    assert "Supply of ERP System" in text
    assert "Acme Ltd" in text and "Punjab Revenue Authority" in text
    body_xml = doc.element.body.xml
    assert 'TOC \\o "1-3"' in body_xml
    upd = doc.settings.element.find(qn("w:updateFields"))
    assert upd is not None and upd.get(qn("w:val")) == "true"


def test_builder_sections_not_rendered_from_content() -> None:
    text = all_text(build())
    assert "SHOULD NOT RENDER" not in text
    assert text.count("Annex A — Compliance Matrix") == 1


def test_markdown_rendering() -> None:
    doc = build()
    paras = doc.paragraphs
    h1 = [p.text for p in paras if p.style is not None and p.style.name == "Heading 1"]
    assert "Technical Solution" in h1 and h1.count("Technical Solution") == 1  # dup title dropped
    assert "Team Composition" in h1
    h3 = [p.text for p in paras if p.style is not None and p.style.name == "Heading 3"]
    assert "Components" in h3
    intro = next(p for p in paras if p.text.startswith("Intro paragraph"))
    assert intro.text.endswith("a continued line.")
    assert any(r.bold and r.text == "bold text" for r in intro.runs)
    assert any(r.italic and r.text == "italic text" for r in intro.runs)
    assert any(r.bold and r.italic and r.text == "both" for r in intro.runs)
    assert any(r.font.name == "Consolas" and r.text == "code" for r in intro.runs)
    styles = {p.text: p.style.name for p in paras if p.style is not None}
    assert styles["First bullet"] == "List Bullet"
    assert styles["Nested bullet"] == "List Bullet 2"
    assert styles["Step one"] == "List Number"
    assert styles["A quoted note"] == "Quote"
    assert "code block line" in styles


def test_numbered_lists_restart() -> None:
    doc = build()

    def num_id(text: str) -> str | None:
        p = next(p for p in doc.paragraphs if p.text == text)
        num_pr = p._p.pPr.numPr if p._p.pPr is not None else None
        return None if num_pr is None else str(num_pr.numId.val)

    assert num_id("Step one") == num_id("Step two")
    assert num_id("Step one") is not None
    assert num_id("Again one") != num_id("Step one")


def test_placeholder_highlighted() -> None:
    doc = build()
    p = next(p for p in doc.paragraphs if "server count" in p.text)
    assert has_highlighted_placeholder(p)
    run = next(r for r in p.runs if "CLIENT INPUT REQUIRED" in r.text)
    assert run.font.highlight_color == WD_COLOR_INDEX.YELLOW


def test_markdown_table_and_annexes() -> None:
    doc = build()
    tables = doc.tables
    md_table = tables[0]
    assert md_table.rows[0].cells[0].text == "Component"
    assert md_table.rows[2].cells[1].text == "PostgreSQL"
    assert md_table.style is not None and md_table.style.name == "Table Grid"
    annex_a = next(t for t in tables if t.rows[0].cells[0].text == "Req Code")
    assert [c.text for c in annex_a.rows[0].cells] == [
        "Req Code", "Requirement", "Status", "Evidence", "Source Page",
    ]
    assert annex_a.rows[1].cells[2].text == "COMPLIANT"
    assert "(mandatory)" in annex_a.rows[1].cells[1].text
    assert annex_a.rows[2].cells[2].text == "PARTIAL"
    assert annex_a.rows[2].cells[3].text == "—"
    form_tables = [t for t in tables if t.rows[0].cells[0].text == "Field"]
    tech, fin = form_tables
    assert tech.rows[1].cells[1].text == "Acme Ltd"
    assert tech.rows[2].cells[1].text == "[CLIENT INPUT REQUIRED: Signature]"
    assert tech.rows[3].cells[1].text == "Not applicable"
    assert "1,000,000" not in all_text(doc)  # financial form values never printed
    assert fin.rows[1].cells[1].text == "—"


def test_citations_only_when_requested() -> None:
    assert "Evidence Reference List" not in all_text(build(include_citations=False))
    text = all_text(build(include_citations=True))
    assert "Evidence Reference List" in text
    assert "EV-CAP-001" in text


def test_minimal_inputs() -> None:
    data = build_proposal_docx(
        TenderMetadata(), None, [], [], [], [], draft=False, include_citations=True
    )
    doc = Document(BytesIO(data))
    text = all_text(doc)
    assert "[CLIENT INPUT REQUIRED: submitted by]" in text
    assert "No prescribed forms" in text
    assert "No citations recorded." in text
    assert "N/A" in doc.sections[0].header.paragraphs[0].text
