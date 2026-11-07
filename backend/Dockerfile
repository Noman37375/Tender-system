FROM python:3.12-slim
# tesseract-ocr: OCR fallback for image-only PDF pages (PRD 7.3 ingest). DOCX is parsed with
# python-docx, so LibreOffice is not needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN useradd --create-home app && mkdir -p /data/files && chown app /data/files
USER app
EXPOSE 8000
# Migrations apply on start, so `docker compose up` gives a ready database.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
