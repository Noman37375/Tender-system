from pydantic import BaseModel


class PageText(BaseModel):
    """One extracted page, as handed to LLM agents (loaded from document_pages)."""

    document_id: str
    page_no: int
    text: str
    tables: list[dict[str, list[list[str | None]]]] = []
