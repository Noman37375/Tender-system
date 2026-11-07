"""Compliance workbook (PRD 12). OWNER: rules agent.

Sheets: Compliance (auto-filter + conditional status colours), Missing Information (severity
colours), Evidence Register. Text that would be read as a formula (=, +, -, @) is forced to a
string so uploaded document text can never become a spreadsheet formula.
"""

import json
from io import BytesIO
from typing import Any

from openpyxl import Workbook  # type: ignore[import-untyped]
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE  # type: ignore[import-untyped]
from openpyxl.formatting.rule import FormulaRule  # type: ignore[import-untyped]
from openpyxl.styles import Alignment, Font, PatternFill  # type: ignore[import-untyped]
from openpyxl.utils import get_column_letter  # type: ignore[import-untyped]
from openpyxl.worksheet.worksheet import Worksheet  # type: ignore[import-untyped]

from app.schemas.compliance import ComplianceRecord, MissingInfo
from app.schemas.evidence import EvidenceItem
from app.schemas.tender import Requirement

STATUS_FILLS: dict[str, str] = {
    "COMPLIANT": "C6EFCE",  # green
    "PARTIAL": "FFEB9C",  # amber
    "NON_COMPLIANT": "FFC7CE",  # red
    "UNVERIFIED": "D9D9D9",  # grey
}
SEVERITY_FILLS: dict[str, str] = {
    "BLOCKER": "FFC7CE",
    "HIGH": "F8CBAD",
    "MEDIUM": "FFEB9C",
    "LOW": "DDEBF7",
}
VERIFICATION_FILLS: dict[str, str] = {
    "DOCUMENTED": "C6EFCE",
    "SELF_DECLARED": "FFEB9C",
    "EXPIRED": "FFC7CE",
    "UNVERIFIED": "D9D9D9",
}
_HEADER_FILL = PatternFill("solid", start_color="1F3864", end_color="1F3864")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int | float):
        return value
    text = ILLEGAL_CHARACTERS_RE.sub("", str(value))
    return text[:32000]  # Excel cell limit is 32,767 chars


def _write_sheet(
    ws: Worksheet,
    headers: list[str],
    rows: list[list[Any]],
    widths: list[int],
) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row_idx, row in enumerate(rows, start=2):
        for col_idx, raw in enumerate(row, start=1):
            value = _safe(raw)
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
                cell.data_type = "s"  # never a formula
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    last_col = get_column_letter(len(headers))
    ws.auto_filter.ref = f"A1:{last_col}{max(len(rows) + 1, 2)}"
    ws.freeze_panes = "A2"


def _colour_by_value(ws: Worksheet, column: str, n_cols: int, fills: dict[str, str]) -> None:
    last_row = max(ws.max_row, 2)
    rng = f"A2:{get_column_letter(n_cols)}{last_row}"
    for value, colour in fills.items():
        ws.conditional_formatting.add(
            rng,
            FormulaRule(
                formula=[f'${column}2="{value}"'],
                fill=PatternFill("solid", start_color=colour, end_color=colour),
            ),
        )


def build_compliance_xlsx(
    requirements: list[Requirement],
    records: list[ComplianceRecord],
    missing: list[MissingInfo],
    evidence: list[EvidenceItem],
) -> bytes:
    wb = Workbook()
    by_code = {r.req_code: r for r in records}
    req_by_code = {r.req_code: r for r in requirements}

    ws = wb.active
    assert ws is not None
    ws.title = "Compliance"
    headers = [
        "Req Code",
        "Category",
        "Requirement",
        "Mandatory",
        "Status",
        "LLM Proposed",
        "Rule",
        "Evidence Codes",
        "Rationale",
        "Gap",
        "Action Required",
        "Source Page",
    ]
    rows: list[list[Any]] = []
    ordered = [r.req_code for r in requirements] + [
        c for c in by_code if c not in req_by_code
    ]  # orphan records still shown
    for code in ordered:
        req = req_by_code.get(code)
        rec = by_code.get(code)
        rows.append(
            [
                code,
                req.category.value if req else None,
                req.description if req else None,
                req.is_mandatory if req else None,
                rec.status.value if rec else "MISSING RECORD",
                rec.llm_proposed_status.value if rec else None,
                rec.rule_applied if rec else None,
                ", ".join(rec.evidence_codes) if rec else None,
                rec.rationale if rec else None,
                rec.gap_description if rec else None,
                rec.action_required if rec else None,
                req.source.page if req else None,
            ]
        )
    _write_sheet(ws, headers, rows, [11, 15, 60, 11, 16, 16, 7, 22, 50, 40, 40, 11])
    _colour_by_value(ws, "$E", len(headers), STATUS_FILLS)

    ws2 = wb.create_sheet("Missing Information")
    headers2 = ["Severity", "Req Code", "Item", "Reason"]
    order = {"BLOCKER": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    rows2 = [
        [m.severity, m.req_code, m.item, m.reason]
        for m in sorted(missing, key=lambda m: order.get(m.severity, 9))
    ]
    _write_sheet(ws2, headers2, rows2, [12, 11, 60, 60])
    _colour_by_value(ws2, "$A", len(headers2), SEVERITY_FILLS)

    ws3 = wb.create_sheet("Evidence Register")
    headers3 = [
        "Evidence Code",
        "Category",
        "Description",
        "Verification Status",
        "Attributes",
        "Document",
        "Page",
        "Source Quote",
    ]
    rows3 = [
        [
            e.evidence_code,
            e.category.value,
            e.description,
            e.verification_status.value,
            json.dumps(e.attributes, default=str, ensure_ascii=False),
            e.source.document_id,
            e.source.page,
            e.source.quote,
        ]
        for e in evidence
    ]
    _write_sheet(ws3, headers3, rows3, [14, 20, 50, 18, 50, 38, 7, 60])
    _colour_by_value(ws3, "$D", len(headers3), VERIFICATION_FILLS)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
