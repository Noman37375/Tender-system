"""Build small PDF/DOCX samples in memory (no binary fixtures in the repo)."""

import io

import docx
import pymupdf

TABLE_ROWS = [["Item", "Qty", "Unit"], ["Core switch", "2", "pcs"], ["Access point", "40", "pcs"]]


def pdf_bytes(pages: list[str], table_on_page: int | None = None) -> bytes:
    """One PDF page per string; optionally draw a ruled 3x3 table (TABLE_ROWS) on a page."""
    doc = pymupdf.open()
    for index, text in enumerate(pages, start=1):
        page = doc.new_page()
        y = 72
        for line in text.splitlines():
            page.insert_text((72, y), line, fontsize=11)
            y += 16
        if table_on_page == index:
            _draw_table(page, top=max(y + 20, 300))
    data = doc.tobytes()
    doc.close()
    return data


def _draw_table(page: pymupdf.Page, top: float) -> None:
    left, col_w, row_h = 72, 150, 24
    n_rows, n_cols = len(TABLE_ROWS), len(TABLE_ROWS[0])
    for r in range(n_rows + 1):
        y = top + r * row_h
        page.draw_line((left, y), (left + n_cols * col_w, y))
    for c in range(n_cols + 1):
        x = left + c * col_w
        page.draw_line((x, top), (x, top + n_rows * row_h))
    for r, row in enumerate(TABLE_ROWS):
        for c, cell in enumerate(row):
            page.insert_text((left + c * col_w + 6, top + r * row_h + 16), cell, fontsize=10)


def image_only_pdf(n_pages: int = 1) -> bytes:
    """Pages that carry only an image (a 'scan'), no text layer."""
    doc = pymupdf.open()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 60, 60), False)
    pix.clear_with(200)
    png = pix.tobytes("png")
    for _ in range(n_pages):
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(72, 72, 300, 300), stream=png)
    data = doc.tobytes()
    doc.close()
    return data


def mixed_pdf(text_pages: int, image_pages: int) -> bytes:
    doc = pymupdf.open(stream=pdf_bytes([f"Text page {i + 1}" for i in range(text_pages)]))
    doc.insert_pdf(pymupdf.open(stream=image_only_pdf(image_pages)))
    data = doc.tobytes()
    doc.close()
    return data


def js_pdf() -> bytes:
    doc = pymupdf.open(stream=pdf_bytes(["Harmless looking page"]))
    doc.xref_set_key(doc.pdf_catalog(), "OpenAction", "<</S/JavaScript/JS(app.alert(1))>>")
    data = doc.tobytes()
    doc.close()
    return data


def embedded_file_pdf() -> bytes:
    doc = pymupdf.open(stream=pdf_bytes(["Page with attachment"]))
    doc.embfile_add("payload.txt", b"hidden content")
    data = doc.tobytes()
    doc.close()
    return data


def encrypted_pdf() -> bytes:
    doc = pymupdf.open(stream=pdf_bytes(["Secret"]))
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    return data


def docx_bytes(
    blocks: list[tuple[str, str]], table: list[list[str]] | None = None, macro: bool = False
) -> bytes:
    """blocks: (style, text) where style is 'h1', 'h2' or 'p'."""
    document = docx.Document()
    for style, text in blocks:
        if style == "h1":
            document.add_heading(text, level=1)
        elif style == "h2":
            document.add_heading(text, level=2)
        else:
            document.add_paragraph(text)
    if table:
        t = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, cell in enumerate(row):
                t.cell(r, c).text = cell
    buf = io.BytesIO()
    document.save(buf)
    data = buf.getvalue()
    if macro:
        import zipfile

        out = io.BytesIO()
        with (
            zipfile.ZipFile(io.BytesIO(data)) as src,
            zipfile.ZipFile(out, "w") as dst,
        ):
            for item in src.infolist():
                dst.writestr(item, src.read(item.filename))
            dst.writestr("word/vbaProject.bin", b"\x00macro")
        data = out.getvalue()
    return data
