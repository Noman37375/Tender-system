from typing import Literal

from pydantic import BaseModel


class FormField(BaseModel):
    label: str
    value: str | None = None
    evidence_codes: list[str] = []
    status: Literal["FILLED", "NEEDS_INPUT", "NOT_APPLICABLE"]


class TenderForm(BaseModel):
    form_code: str
    title: str
    source_page: int
    envelope: Literal["TECHNICAL", "FINANCIAL", "ELIGIBILITY"]
    fields: list[FormField]


class TenderFormList(BaseModel):
    forms: list[TenderForm]
