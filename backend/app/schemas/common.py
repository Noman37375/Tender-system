from enum import StrEnum

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    document_id: str
    page: int = Field(ge=1)
    quote: str = Field(max_length=500, description="Verbatim span from the source page")


class Confidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
