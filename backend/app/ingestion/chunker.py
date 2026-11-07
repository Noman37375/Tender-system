"""Heading-aware chunking (PRD 7.3 ingest step 4).

Target ~800 tokens with ~100 tokens of overlap, tokens approximated as len(text) / 4. Chunks
never cross a document (one call = one document) and record page_start/page_end. A heading
starts a new chunk with no overlap from the previous section; inside a section, consecutive
chunks share an overlap tail.
"""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

TARGET_TOKENS = 800
OVERLAP_TOKENS = 100
CHARS_PER_TOKEN = 4
MAX_HEADING_CHARS = 120
MAX_HEADING_WORDS = 12

_NUMBERED = re.compile(r"^(\d+(\.\d+)*\.?|[A-Z]\.|[IVXLC]+\.)\s+\S")
_KEYWORD = re.compile(
    r"^(section|part|chapter|annex|annexure|appendix|schedule|article|lot)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class PageInput:
    page_no: int
    text: str
    # Lines known to be headings (DOCX heading styles). None = detect headings heuristically.
    headings: frozenset[str] | None = None


@dataclass(frozen=True)
class ChunkDraft:
    page_start: int
    page_end: int
    section_heading: str | None
    content: str
    token_count: int


@dataclass(frozen=True)
class _Unit:
    page_no: int
    text: str
    is_heading: bool = False
    overlap: bool = False

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def _title_like(words: list[str]) -> bool:
    long_words = [w for w in words if len(w) > 3 and w[0].isalpha()]
    if not long_words:
        return True
    capitalised = sum(1 for w in long_words if w[0].isupper())
    return capitalised / len(long_words) >= 0.5


def is_heading_line(line: str) -> bool:
    """Heuristic heading detector for extracted PDF text lines."""
    text = line.strip()
    if not (3 <= len(text) <= MAX_HEADING_CHARS) or text[-1] in ".,;":
        return False
    words = text.split()
    if len(words) > MAX_HEADING_WORDS:
        return False
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 3:
        return False
    if all(c.isupper() for c in letters) and len(letters) >= 4:
        return True
    if _NUMBERED.match(text) or _KEYWORD.match(text):
        return _title_like(words[1:])
    return False


def _split_long(page_no: int, text: str, max_tokens: int) -> list[_Unit]:
    """Cut a paragraph longer than max_tokens into word-boundary windows."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    units: list[_Unit] = []
    current: list[str] = []
    size = 0
    for word in text.split():
        if current and size + 1 + len(word) > max_chars:
            units.append(_Unit(page_no, " ".join(current)))
            current, size = [], 0
        current.append(word)
        size += len(word) + (1 if size else 0)
    if current:
        units.append(_Unit(page_no, " ".join(current)))
    return units


def _paragraph_units(page_no: int, lines: list[str], max_tokens: int) -> list[_Unit]:
    if not lines:
        return []
    text = "\n".join(lines)
    if estimate_tokens(text) > max_tokens:
        return _split_long(page_no, text, max_tokens)
    return [_Unit(page_no, text)]


def _units(pages: Iterable[PageInput], max_tokens: int) -> list[_Unit]:
    units: list[_Unit] = []
    for page in pages:
        paragraph: list[str] = []
        for raw in page.text.splitlines():
            line = raw.strip()
            heading = line and (
                is_heading_line(line) if page.headings is None else line in page.headings
            )
            if not line or heading:
                units.extend(_paragraph_units(page.page_no, paragraph, max_tokens))
                paragraph = []
                if heading:
                    units.append(_Unit(page.page_no, line, is_heading=True))
            else:
                paragraph.append(line)
        units.extend(_paragraph_units(page.page_no, paragraph, max_tokens))
    return units


def _overlap_tail(units: Sequence[_Unit], overlap_tokens: int) -> list[_Unit]:
    if overlap_tokens <= 0 or not units:
        return []
    tail: list[_Unit] = []
    total = 0
    for unit in reversed(units):
        if total + unit.tokens > overlap_tokens:
            break
        tail.insert(0, _Unit(unit.page_no, unit.text, overlap=True))
        total += unit.tokens
    if tail:
        return tail
    last = units[-1]  # a single unit bigger than the overlap: take its last words
    max_chars = overlap_tokens * CHARS_PER_TOKEN
    piece = last.text[-max_chars:]
    if len(piece) < len(last.text) and " " in piece:
        piece = piece.split(" ", 1)[1]
    return [_Unit(last.page_no, piece.strip(), overlap=True)]


def chunk_pages(
    pages: Sequence[PageInput],
    target_tokens: int = TARGET_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
) -> list[ChunkDraft]:
    """Chunk the pages of ONE document."""
    if overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be smaller than target_tokens")
    chunks: list[ChunkDraft] = []
    current: list[_Unit] = []
    heading: str | None = None

    def has_fresh() -> bool:
        return any(not u.overlap for u in current)

    def emit() -> None:
        if not has_fresh():
            return
        content = "\n".join(u.text for u in current)
        chunks.append(
            ChunkDraft(
                page_start=min(u.page_no for u in current),
                page_end=max(u.page_no for u in current),
                section_heading=heading,
                content=content,
                token_count=max(1, estimate_tokens(content)),
            )
        )

    for unit in _units(pages, target_tokens - overlap_tokens):
        if unit.is_heading:
            if current and all(u.is_heading for u in current):
                current.append(unit)  # stacked headings ("PART II" / "3.1 Scope") stay together
            else:
                emit()
                current = [unit]
            heading = unit.text
            continue
        size = sum(u.tokens for u in current)
        if current and has_fresh() and size + unit.tokens > target_tokens:
            emit()
            current = _overlap_tail(current, overlap_tokens)
        current.append(unit)
    emit()
    return chunks
