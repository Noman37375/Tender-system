"""Proposal DOCX (PRD 12). OWNER: rules agent.

A4, 2.5 cm margins, header with the tender reference, footer "Confidential | Page X of Y",
cover page, TOC field (updated on open), sections rendered from markdown, Annex A compliance
matrix, Annex B prescribed forms, optional evidence reference list, DRAFT watermark.
"""

from datetime import date
from io import BytesIO

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_BREAK, WD_PARAGRAPH_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.section import Section
from docx.shared import Cm, Mm, Pt, RGBColor
from docx.table import _Cell
from docx.text.paragraph import Paragraph

from app.export.markdown_docx import add_inline, render_markdown
from app.schemas.compliance import ComplianceRecord
from app.schemas.forms import TenderForm
from app.schemas.proposal import PLACEHOLDER_PREFIX, ProposalSection
from app.schemas.tender import Requirement, TenderMetadata

WATERMARK_TEXT = "DRAFT — NOT FOR SUBMISSION"
BUILDER_SECTIONS = {"cover", "toc", "compliance_annex", "forms_annex"}
_STATUS_COLOURS = {
    "COMPLIANT": "C6EFCE",
    "PARTIAL": "FFEB9C",
    "NON_COMPLIANT": "FFC7CE",
    "UNVERIFIED": "D9D9D9",
}


def _placeholder(label: str) -> str:
    return f"{PLACEHOLDER_PREFIX} {label}]"


# ---------------------------------------------------------------- fields & page setup


def _add_field(paragraph: Paragraph, instr: str, placeholder: str = "") -> None:
    """Complex field (PAGE, NUMPAGES, TOC ...) inside `paragraph`."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    run._r.append(begin)
    run = paragraph.add_run()
    instr_el = OxmlElement("w:instrText")
    instr_el.set(qn("xml:space"), "preserve")
    instr_el.text = f" {instr} "
    run._r.append(instr_el)
    run = paragraph.add_run()
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    run._r.append(sep)
    paragraph.add_run(placeholder)
    run = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(end)


def _set_update_fields_on_open(doc: DocxDocument) -> None:
    settings = doc.settings.element
    existing = settings.find(qn("w:updateFields"))
    if existing is None:
        existing = OxmlElement("w:updateFields")
        settings.append(existing)
    existing.set(qn("w:val"), "true")


def _setup_page(section: Section) -> None:
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(2.5))


def _header_footer(section: Section, reference: str, draft: bool) -> None:
    header_p = section.header.paragraphs[0]
    header_p.text = f"Tender reference: {reference}"
    header_p.alignment = WD_PARAGRAPH_ALIGNMENT.RIGHT
    for run in header_p.runs:
        run.font.size = Pt(9)
    if draft:
        _add_watermark(section)

    footer_p = section.footer.paragraphs[0]
    footer_p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
    footer_p.add_run("Confidential  |  Page ")
    _add_field(footer_p, "PAGE", "1")
    footer_p.add_run(" of ")
    _add_field(footer_p, "NUMPAGES", "1")
    for run in footer_p.runs:
        run.font.size = Pt(9)


def _add_watermark(section: Section) -> None:
    """Diagonal VML text watermark in the header (how Word itself stores watermarks)."""
    xml = (
        '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:o="urn:schemas-microsoft-com:office:office">'
        "<w:r><w:pict>"
        '<v:shapetype id="_x0000_t136" coordsize="21600,21600" o:spt="136" adj="10800" '
        'path="m@7,l@8,m@5,21600l@6,21600e">'
        '<v:path textpathok="t" o:connecttype="custom"/>'
        '<v:textpath on="t" fitshape="t"/>'
        "</v:shapetype>"
        '<v:shape id="PowerPlusWaterMarkObject" o:spid="_x0000_s2049" type="#_x0000_t136" '
        'style="position:absolute;margin-left:0;margin-top:0;width:468pt;height:78pt;'
        "rotation:315;z-index:-251654144;mso-position-horizontal:center;"
        "mso-position-horizontal-relative:margin;mso-position-vertical:center;"
        'mso-position-vertical-relative:margin" fillcolor="#d8d8d8" stroked="f">'
        '<v:fill opacity=".5"/>'
        f'<v:textpath style="font-family:&quot;Calibri&quot;;font-size:1pt" '
        f'string="{WATERMARK_TEXT}"/>'
        "</v:shape>"
        "</w:pict></w:r></w:p>"
    )
    section.header._element.append(parse_xml(xml))


# ---------------------------------------------------------------- building blocks


def _page_break(doc: DocxDocument) -> None:
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _shade(cell: _Cell, colour: str) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), colour)
    tc_pr.append(shd)


def _table(doc: DocxDocument, headers: list[str], rows: list[list[str]]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for idx, text in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        _shade(cell, "D9E2F3")
    for row in rows:
        cells = table.add_row().cells
        for idx, text in enumerate(row):
            cells[idx].text = ""
            add_inline(cells[idx].paragraphs[0], text)


def _cover(doc: DocxDocument, metadata: TenderMetadata, company_name: str | None) -> None:
    for _ in range(6):
        doc.add_paragraph()
    title = doc.add_paragraph(style="Title")
    title.add_run("Technical Proposal")
    title.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    def line(label: str, value: str | None, size: int = 14, bold: bool = False) -> None:
        p = doc.add_paragraph()
        p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
        if label:
            r = p.add_run(f"{label}: ")
            r.font.size = Pt(size)
            r.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
        if value:
            v = p.add_run(value)
            v.font.size = Pt(size)
            v.bold = bold
        else:
            add_inline(p, _placeholder(label.lower() if label else "value"))

    line("", metadata.title or "Untitled tender", size=18, bold=True)
    doc.add_paragraph()
    line("Submitted by", company_name, bold=True)
    line("Tender reference", metadata.reference_no)
    line("Procuring entity", metadata.procuring_entity)
    line("Date", date.today().strftime("%d %B %Y"))
    _page_break(doc)


def _toc(doc: DocxDocument) -> None:
    doc.add_heading("Table of Contents", level=1)
    p = doc.add_paragraph()
    _add_field(p, 'TOC \\o "1-3" \\h \\z \\u', "Right-click and choose Update Field.")
    _page_break(doc)


def _section(doc: DocxDocument, section: ProposalSection) -> None:
    doc.add_heading(section.title, level=1)
    content = section.content_md.strip()
    first = content.splitlines()[0].strip() if content else ""
    if first.startswith("#") and first.lstrip("#").strip().lower() == section.title.lower():
        content = "\n".join(content.splitlines()[1:])  # avoid a duplicated title heading
    render_markdown(doc, content)


def _annex_a(
    doc: DocxDocument, requirements: list[Requirement], records: list[ComplianceRecord]
) -> None:
    doc.add_heading("Annex A — Compliance Matrix", level=1)
    by_code = {r.req_code: r for r in records}
    table = doc.add_table(rows=1, cols=5)
    table.style = "Table Grid"
    for idx, text in enumerate(["Req Code", "Requirement", "Status", "Evidence", "Source Page"]):
        cell = table.rows[0].cells[idx]
        cell.text = ""
        cell.paragraphs[0].add_run(text).bold = True
        _shade(cell, "D9E2F3")
    for req in requirements:
        rec = by_code.get(req.req_code)
        status = rec.status.value if rec else "UNVERIFIED"
        evidence = ", ".join(rec.evidence_codes) if rec and rec.evidence_codes else "—"
        mandatory = " (mandatory)" if req.is_mandatory else ""
        cells = table.add_row().cells
        cells[0].text = req.req_code
        cells[1].text = f"{req.description}{mandatory}"
        cells[2].text = status.replace("_", " ")
        _shade(cells[2], _STATUS_COLOURS.get(status, "FFFFFF"))
        cells[3].text = evidence
        cells[4].text = str(req.source.page)


def _annex_b(doc: DocxDocument, forms: list[TenderForm]) -> None:
    doc.add_heading("Annex B — Prescribed Forms", level=1)
    if not forms:
        doc.add_paragraph("No prescribed forms were detected in the tender documents.")
        return
    for form in forms:
        doc.add_heading(f"{form.form_code} — {form.title}", level=2)
        doc.add_paragraph(f"Envelope: {form.envelope.title()}  |  Tender page {form.source_page}")
        if form.envelope == "FINANCIAL":
            doc.add_paragraph(
                "Financial form: to be completed by the bidder in the financial proposal. "
                "No values are filled in the technical proposal."
            )
            rows = [[f.label, "—", "Financial proposal"] for f in form.fields]
        else:
            rows = []
            for f in form.fields:
                if f.status == "FILLED" and f.value:
                    value = f.value
                elif f.status == "NOT_APPLICABLE":
                    value = "Not applicable"
                else:
                    value = _placeholder(f.label)
                rows.append([f.label, value, f.status.replace("_", " ").title()])
        _table(doc, ["Field", "Value", "Status"], rows)


def _citations(doc: DocxDocument, sections: list[ProposalSection]) -> None:
    doc.add_heading("Evidence Reference List (internal review copy)", level=1)
    rows = [
        [s.title, c.claim, ", ".join(c.evidence_codes) or "—", ", ".join(c.req_codes) or "—"]
        for s in sections
        for c in s.citations
    ]
    if not rows:
        doc.add_paragraph("No citations recorded.")
        return
    _table(doc, ["Section", "Claim", "Evidence", "Requirements"], rows)


def build_proposal_docx(
    metadata: TenderMetadata,
    company_name: str | None,
    sections: list[ProposalSection],  # in order; cover/toc/annexes rendered by the builder
    requirements: list[Requirement],
    records: list[ComplianceRecord],
    forms: list[TenderForm],
    draft: bool,  # True -> watermark "DRAFT - NOT FOR SUBMISSION"
    include_citations: bool = False,
) -> bytes:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    _set_update_fields_on_open(doc)
    _setup_page(doc.sections[0])
    _header_footer(doc.sections[0], metadata.reference_no or "N/A", draft)
    doc.core_properties.title = metadata.title or "Technical Proposal"
    doc.core_properties.subject = metadata.reference_no or ""

    _cover(doc, metadata, company_name)
    _toc(doc)
    body = [s for s in sections if s.section_key not in BUILDER_SECTIONS]
    for idx, section in enumerate(body):
        _section(doc, section)
        if idx < len(body) - 1:
            _page_break(doc)
    _page_break(doc)
    _annex_a(doc, requirements, records)
    _page_break(doc)
    _annex_b(doc, forms)
    if include_citations:
        _page_break(doc)
        _citations(doc, sections)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
