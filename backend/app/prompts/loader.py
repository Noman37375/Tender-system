"""Prompt loading, rendering and untrusted-content wrapping (PRD 9, Appendix A).

File format (`app/prompts/<name>.md`):

    ---
    version: 1
    ---
    <system template>
    === USER ===
    <user template>

The system part holds only our own instructions; the A.0 security clause is prepended to it.
Everything derived from uploaded documents (page text, requirement/evidence descriptions,
quotes) goes into the user part, wrapped in <document> blocks, so it can never be mistaken for
system instructions (rule 10, S-05). `{{var}}` placeholders are filled in one pass; a missing
variable raises KeyError.
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.pages import PageText

PROMPT_DIR = Path(__file__).resolve().parent
USER_MARKER = "=== USER ==="
SECURITY_CLAUSE_NAME = "shared_security"

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_VERSION = re.compile(r"^version:\s*(\S+)\s*$", re.MULTILINE)
_VAR = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_DOC_TAG = re.compile(r"<(/?)(document)", re.IGNORECASE)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system_template: str
    user_template: str

    @property
    def prompt_version(self) -> str:
        return f"{self.name}@{self.version}"

    def system(self, **variables: Any) -> str:
        """A.0 security clause + this prompt's system part."""
        body = render(self.system_template, variables)
        return f"{security_clause()}\n\n{body}".strip()

    def user(self, **variables: Any) -> str:
        return render(self.user_template, variables)


def render(template: str, variables: dict[str, Any]) -> str:
    def sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            raise KeyError(f"Prompt variable '{key}' was not provided")
        value = variables[key]
        return "" if value is None else str(value)

    return _VAR.sub(sub, template)


def parse_prompt(name: str, text: str) -> Prompt:
    match = _FRONT_MATTER.match(text)
    if not match:
        raise ValueError(f"Prompt '{name}' has no front matter")
    version_match = _VERSION.search(match.group(1))
    if not version_match:
        raise ValueError(f"Prompt '{name}' has no 'version:' line")
    body = text[match.end() :]
    system_part, _, user_part = body.partition(USER_MARKER)
    return Prompt(
        name=name,
        version=version_match.group(1),
        system_template=system_part.strip(),
        user_template=user_part.strip(),
    )


@lru_cache
def load_prompt(name: str) -> Prompt:
    path = PROMPT_DIR / f"{name}.md"
    return parse_prompt(name, path.read_text(encoding="utf-8"))


def security_clause() -> str:
    return load_prompt(SECURITY_CLAUSE_NAME).system_template


# ------------------------------------------------------------------ untrusted content wrapping
def escape_document_text(text: str) -> str:
    """Neutralise literal <document / </document inside untrusted text so it cannot close or
    open a block. Only the tag name is touched; the rest of the text is kept verbatim."""
    return _DOC_TAG.sub(lambda m: f"&lt;{m.group(1)}{m.group(2)}", text)


def _attr(value: object) -> str:
    return str(value).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def wrap_document(document_id: str, page: int | str, text: str) -> str:
    return (
        f'<document id="{_attr(document_id)}" page="{_attr(page)}">\n'
        f"{escape_document_text(text)}\n</document>"
    )


def page_text_with_tables(page: PageText) -> str:
    parts = [page.text]
    for index, table in enumerate(page.tables, start=1):
        rows = table.get("rows", [])
        lines = [" | ".join("" if cell is None else str(cell) for cell in row) for row in rows]
        if lines:
            parts.append(f"[Table {index}]\n" + "\n".join(lines))
    return "\n\n".join(p for p in parts if p)


def wrap_page(page: PageText) -> str:
    return wrap_document(page.document_id, page.page_no, page_text_with_tables(page))


def wrap_pages(pages: list[PageText]) -> str:
    return "\n\n".join(wrap_page(p) for p in pages)


def to_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1, default=str)


def wrap_data(name: str, obj: Any) -> str:
    """Structured inputs that contain document-derived text (requirement descriptions, quotes,
    evidence) are untrusted too: JSON inside a <document> block marked page="structured"."""
    return wrap_document(name, "structured", to_json(obj))
