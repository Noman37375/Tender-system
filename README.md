# TenderIQ

Tender eligibility check, bid/no-bid decision and evidence-backed proposal drafting, with human
approval. Specification: [`docs/TECHNICAL_PRD.md`](docs/TECHNICAL_PRD.md). Build rules:
[`docs/MASTER_PROMPT.md`](docs/MASTER_PROMPT.md). Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md).

**Status:** milestone M0 (foundation) done: auth, full database schema, health checks, login and
dashboard pages.

## Run with Docker

```bash
cp .env.example .env        # then set JWT_SECRET (and API keys from M2 on)
docker compose up -d --build
```

| Service | URL (default ports) |
|---|---|
| Frontend | http://localhost:3000 |
| API | http://localhost:8000/api/v1 |
| Health | http://localhost:8000/healthz, http://localhost:8000/readyz |

If ports are taken, set `DB_PORT`, `BACKEND_PORT`, `FRONTEND_PORT` and `NEXT_PUBLIC_API_URL`,
`CORS_ORIGINS` in `.env`. Migrations run automatically when the backend starts.
`/readyz` returns 503 until the LLM and embedding API keys are set; that is expected in M0.

## Develop locally

Needs Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 20+, Docker (for Postgres).

```bash
docker compose up -d db
cd backend
cp ../.env .env             # DATABASE_URL must point at localhost
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev
```

## Tests and checks

```bash
cd backend
uv run pytest               # uses the tenderiq_test database in the compose Postgres
uv run ruff check . && uv run mypy app

cd ../frontend
npm run lint && npx tsc --noEmit
```

## Layout

```
backend/   FastAPI app (routers → services → repositories → models), Alembic, tests
frontend/  Next.js 15 App Router, Tailwind, TanStack Query; lib/api.ts is the only API client
docs/      PRD, master prompt, decisions log
```
