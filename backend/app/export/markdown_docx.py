"""Markdown -> python-docx converter for proposal sections (PRD 12).

Supported: headings (# -> Heading 2 .. capped at Heading 3, because the section title is
Heading 1), paragraphs, **bold**, *italic*, ***both***, `code`, bullet and numbered lists (two
levels, numbering restarts per list), pipe tables, block quotes, fenced code, horizontal rules.
[CLIENT INPUT REQUIRED: ...] placeholders are highlighted yellow.
"""

import re

from docx.document import Document as DocxDocument
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt
from docx.text.paragraph import Paragraph

PLACEHOLDER_RE = re.compile(r"\[CLIENT INPUT REQUIRED:[^\]]*\]")
_INLINE_RE = re.compile(
    r"\*\*\*(?P<bi>.+?)\*\*\*"
    r"|\*\*(?P<b>.+?)\*\*"
    r"|__(?P<b2>.+?)__"
    r"|(?<![\w*])\*(?![\s*])(?P<i>.+?)(?<![\s*])\*(?![\w*])"
    r"|(?<![\w_])_(?![\s_])(?P<i2>.+?)(?<![\s_])_(?![\w_])"
    r"|`(?P<code>[^`]+)`"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_NUMBER_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _add_text(paragraph: Paragraph, text: str) -> None:
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            paragraph.add_run(text[pos : m.start()])
        if m.group("bi") is not None:
            run = paragraph.add_run(m.group("bi"))
            run.bold = True
            run.italic = True
        elif m.group("b") is not None or m.group("b2") is not None:
            paragraph.add_run(m.group("b") or m.group("b2")).bold = True
        elif m.group("i") is not None or m.group("i2") is not None:
            paragraph.add_run(m.group("i") or m.group("i2")).italic = True
        else:
            run = paragraph.add_run(m.group("code"))
            run.font.name = "Consolas"
        pos = m.end()
    if pos < len(text):
        paragraph.add_run(text[pos:])


def add_inline(paragraph: Paragraph, text: str) -> None:
    """Inline markdown into `paragraph`; placeholders get a yellow highlight."""
    pos = 0
    for m in PLACEHOLDER_RE.finditer(text):
        if m.start() > pos:
            _add_text(paragraph, text[pos : m.start()])
        run = paragraph.add_run(m.group(0))
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
        run.bold = True
        pos = m.end()
    if pos < len(text):
        _add_text(paragraph, text[pos:])


def _split_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip() for c in stripped.split("|")]


def _new_list_num_id(doc: DocxDocument, style_name: str) -> int | None:
    """A fresh w:num for `style_name` restarting at 1, so each numbered list starts over."""
    try:
        style = doc.styles[style_name]
    except KeyError:
        return None
    ppr = style.element.pPr
    num_pr = ppr.numPr if ppr is not None else None
    if num_pr is None or num_pr.numId is None:
        return None
    base_id = num_pr.numId.val
    numbering = doc.part.numbering_part.element
    abstract_id: int | None = None
    for num in numbering.num_lst:
        if num.numId == base_id:
            abstract_id = num.abstractNumId.val
            break
    if abstract_id is None:
        return None
    new_num = numbering.add_num(abstract_id)
    new_num.add_lvlOverride(ilvl=0).add_startOverride(1)
    return int(new_num.numId)


def _apply_num(paragraph: Paragraph, num_id: int, level: int) -> None:
    num_pr = paragraph._p.get_or_add_pPr().get_or_add_numPr()
    num_pr.get_or_add_ilvl().val = level
    num_pr.get_or_add_numId().val = num_id


def _add_table(doc: DocxDocument, rows: list[list[str]]) -> None:
    width = max(len(r) for r in rows)
    table = doc.add_table(rows=0, cols=width)
    table.style = "Table Grid"
    for r_idx, row in enumerate(rows):
        cells = table.add_row().cells
        for c_idx in range(width):
            text = row[c_idx] if c_idx < len(row) else ""
            para = cells[c_idx].paragraphs[0]
            add_inline(para, text)
            if r_idx == 0:
                for run in para.runs:
                    run.bold = True


def render_markdown(doc: DocxDocument, md: str) -> None:
    lines = md.replace("\r\n", "\n").split("\n")
    buffer: list[str] = []
    list_kind: str | None = None  # "bullet" | "number"
    num_ids: dict[int, int | None] = {}

    def flush() -> None:
        if buffer:
            add_inline(doc.add_paragraph(), " ".join(s.strip() for s in buffer))
            buffer.clear()

    def end_list() -> None:
        nonlocal list_kind
        list_kind = None
        num_ids.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush()
            end_list()
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                para = doc.add_paragraph()
                run = para.add_run(lines[i])
                run.font.name = "Consolas"
                run.font.size = Pt(9)
                i += 1
            i += 1
            continue
        if not stripped:
            flush()
            i += 1
            continue
        heading = _HEADING_RE.match(stripped)
        if heading:
            flush()
            end_list()
            level = min(len(heading.group(1)) + 1, 3)
            para = doc.add_heading(level=level)
            add_inline(para, heading.group(2))
            i += 1
            continue
        if _HR_RE.match(stripped):
            flush()
            end_list()
            i += 1
            continue
        if stripped.startswith("|"):
            flush()
            end_list()
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not _TABLE_SEP_RE.match(lines[i]):
                    rows.append(_split_row(lines[i]))
                i += 1
            if rows:
                _add_table(doc, rows)
            continue
        bullet = _BULLET_RE.match(line)
        number = None if bullet else _NUMBER_RE.match(line)
        if bullet or number:
            flush()
            m = bullet or number
            assert m is not None
            level = 1 if len(m.group(1).replace("\t", "    ")) >= 2 else 0
            kind = "bullet" if bullet else "number"
            if kind != list_kind:
                end_list()
                list_kind = kind
            base = "List Bullet" if bullet else "List Number"
            style = base if level == 0 else f"{base} 2"
            para = doc.add_paragraph(style=style)
            if number:
                if level not in num_ids:
                    num_ids[level] = _new_list_num_id(doc, style)
                    if level == 0:
                        num_ids.pop(1, None)
                num_id = num_ids[level]
                if num_id is not None:
                    _apply_num(para, num_id, 0)
            add_inline(para, m.group(2))
            i += 1
            continue
        if stripped.startswith(">"):
            flush()
            end_list()
            para = doc.add_paragraph(style="Quote")
            add_inline(para, stripped.lstrip(">").strip())
            i += 1
            continue
        if list_kind is not None and line.startswith((" ", "\t")):
            # continuation line of the previous list item
            last = doc.paragraphs[-1]
            add_inline(last, " " + stripped)
            i += 1
            continue
        end_list()
        buffer.append(stripped)
        i += 1
    flush()


def has_highlighted_placeholder(paragraph: Paragraph) -> bool:
    return any(
        PLACEHOLDER_RE.search(run.text) and run.font.highlight_color == WD_COLOR_INDEX.YELLOW
        for run in paragraph.runs
    )
