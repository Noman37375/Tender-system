"""Single entry point to PyMuPDF, whose API is untyped: callers get an `Any` document."""

from typing import Any

import pymupdf


def open_pdf(data: bytes) -> Any:
    return pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
