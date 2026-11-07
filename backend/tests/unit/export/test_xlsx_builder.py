from io import BytesIO

from openpyxl import load_workbook  # type: ignore[import-untyped]

from app.export.xlsx_builder import build_compliance_xlsx
from app.schemas.compliance import ComplianceStatus as S
from app.schemas.compliance import MissingInfo
from app.schemas.evidence import EvidenceCategory

from ..rules.factories import ev, record, req


def build() -> bytes:
    reqs = [req("ELG-001"), req("TEC-001", description="=HYPERLINK(\"http://evil\")")]
    recs = [
        record("ELG-001", S.COMPLIANT, codes=["EV-CER-001"]),
        record("TEC-001", S.PARTIAL, action="+Provide proof"),
        record("ORPHAN-1", S.UNVERIFIED),
    ]
    missing = [
        MissingInfo(item="low", reason="r", req_code="TEC-002", severity="LOW"),
        MissingInfo(item="Provide proof", reason="partial", req_code="TEC-001", severity="BLOCKER"),
    ]
    evidence = [
        ev("EV-CER-001", name="ISO 27001", expiry_date="2030-01-01"),
        ev("EV-PRJ-001", EvidenceCategory.PROJECT, description="bad\x01char", value=5),
    ]
    return build_compliance_xlsx(reqs, recs, missing, evidence)


def test_workbook_sheets_and_rows() -> None:
    wb = load_workbook(BytesIO(build()))
    assert wb.sheetnames == ["Compliance", "Missing Information", "Evidence Register"]
    ws = wb["Compliance"]
    assert ws["A1"].value == "Req Code"
    assert ws["E2"].value == "COMPLIANT"
    assert ws["H2"].value == "EV-CER-001"
    assert ws["D2"].value == "Yes"
    assert ws["L2"].value == 3
    assert ws["A4"].value == "ORPHAN-1"  # orphan record still listed
    assert ws.auto_filter.ref == "A1:L4"
    assert ws.freeze_panes == "A2"
    assert len(ws.conditional_formatting) >= 1
    rules = [r for cf in ws.conditional_formatting for r in cf.rules]
    assert len(rules) == 4


def test_formula_injection_is_neutralised() -> None:
    wb = load_workbook(BytesIO(build()))
    ws = wb["Compliance"]
    cell = ws["C3"]
    assert cell.data_type == "s"
    assert cell.value.startswith("=HYPERLINK")
    assert ws["K3"].data_type == "s"


def test_missing_sorted_by_severity_and_evidence_register() -> None:
    wb = load_workbook(BytesIO(build()))
    missing = wb["Missing Information"]
    assert [missing["A2"].value, missing["A3"].value] == ["BLOCKER", "LOW"]
    reg = wb["Evidence Register"]
    assert reg["A2"].value == "EV-CER-001"
    assert reg["D2"].value == "DOCUMENTED"
    assert '"ISO 27001"' in reg["E2"].value
    assert reg["C3"].value == "badchar"  # illegal control char stripped
    assert reg["G2"].value == 3


def test_empty_inputs_still_valid() -> None:
    wb = load_workbook(BytesIO(build_compliance_xlsx([], [], [], [])))
    assert wb["Compliance"].max_row == 1
