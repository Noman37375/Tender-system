"""OCR fallback for image-only pages (PRD 7.3 ingest step 3), via the tesseract binary.

The backend image installs tesseract-ocr. Where the binary is missing (e.g. a developer machine),
`ocr_available()` is False and the pipeline records an "OCR unavailable" warning instead of failing.
"""

import io
from functools import lru_cache
from typing import Any

import pytesseract  # type: ignore[import-untyped]
from PIL import Image

OCR_DPI = 300


@lru_cache(maxsize=1)
def ocr_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
    except Exception:  # TesseractNotFoundError, OSError, version parse errors
        return False
    return True


def ocr_page(page: Any) -> str:
    """Render one PDF page to an image and return the recognised text."""
    pixmap = page.get_pixmap(dpi=OCR_DPI)
    image = Image.open(io.BytesIO(pixmap.tobytes("png")))
    text: str = pytesseract.image_to_string(image)
    return text
