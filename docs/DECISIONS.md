# Decisions log

Choices made where the PRD was silent or ambiguous (MASTER_PROMPT §2.3).

| Date | Question | Choice | Reason |
|---|---|---|---|
| 2026-11-07 | PRD §5 says every table has `created_at`/`updated_at`, but the SQL omits them on most tables. | All tables get both columns. | Follows the stated rule; costs nothing. |
| 2026-11-07 | Password hashing library (PRD §3 lists passlib/bcrypt). | `bcrypt` directly, no passlib. | passlib is unmaintained and breaks with bcrypt ≥ 4.1. Same algorithm. |
| 2026-11-07 | JWT library. | PyJWT, HS256, `type` claim separates access and refresh tokens. | Small, maintained; type claim stops a refresh token being used as an access token. |
| 2026-11-07 | Where the frontend keeps tokens in M0. | `localStorage`, behind `lib/api.ts`. | API is a separate origin, so httpOnly cookies need extra CSRF work. Revisit in M6 hardening (XSS exposure). |
| 2026-11-07 | shadcn/ui in M0. | Not yet; plain Tailwind for the two M0 pages. | Added when real components (tables, dialogs) arrive in M2–M4. |
| 2026-11-07 | Repository location of the PRD. | Kept in `docs/`, not the repo root. | Keeps the root clean; MASTER_PROMPT points to it. |
| 2026-11-07 | Test database. | Separate `tenderiq_test` database, created by `backend/scripts/init-test-db.sql`, migrated once per test session, truncated before each test. | Tests never touch dev data; real Postgres catches constraint bugs. |
| 2026-11-07 | Host ports. | Compose host ports come from `DB_PORT`, `BACKEND_PORT`, `FRONTEND_PORT` (defaults 5432/8000/3000). | 8000 and 3000 were already taken on the dev machine. |

## Notes for M2 (from `D:\multi-agent-narrative-system`)

Patterns to reuse when building `app/llm/`:
- **Fallback chain with cooldown:** classify each LLM error (rate limit, overloaded, key rejected, network) and skip that model for a set time; try the next model. Fits D5 and PRD 7.5.
- **Non-blocking run recorder:** event and step writes go through a queue drained by a background task, so a DB hiccup never fails a run.
- **Reviewer gate with one retry:** same shape as our audit → one revision → human (D9).

Not copied: that project stores full prompts and responses in an `llm_calls` table. PRD S-07 forbids logging full document text, so TenderIQ logs IDs, hashes, token counts and prompt versions only.
