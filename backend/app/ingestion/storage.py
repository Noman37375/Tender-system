"""Local file storage (S-04): UUID file names under STORAGE_PATH, outside the web root.

`documents.storage_path` holds the storage key (the UUID file name), not an absolute path, so the
storage root can move without a data migration and a stored value can never point elsewhere.
"""

import re
import uuid
from pathlib import Path

from app.config import get_settings
from app.ingestion.validation import DOCX_MIME, PDF_MIME

_KEY = re.compile(r"^[0-9a-f]{32}\.(pdf|docx)$")
_EXT = {PDF_MIME: "pdf", DOCX_MIME: "docx"}


def _root() -> Path:
    root = Path(get_settings().STORAGE_PATH)
    root.mkdir(parents=True, exist_ok=True)
    return root


def path_for(key: str) -> Path:
    if not _KEY.fullmatch(key):
        raise ValueError("invalid storage key")
    return _root() / key


def save(data: bytes, mime_type: str) -> str:
    """Write bytes under a fresh UUID name; return the storage key."""
    key = f"{uuid.uuid4().hex}.{_EXT[mime_type]}"
    path_for(key).write_bytes(data)
    return key


def read(key: str) -> bytes:
    return path_for(key).read_bytes()


def remove(key: str) -> None:
    """Delete a stored file; a missing file is not an error."""
    try:
        path_for(key).unlink(missing_ok=True)
    except ValueError:
        return
