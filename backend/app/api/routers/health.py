from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import SessionDep
from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: SessionDep) -> JSONResponse:
    """Readiness: database reachable and required LLM/embedding keys present (PRD §14)."""
    checks: dict[str, str] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # report, don't crash the probe
        checks["database"] = "unreachable"
    missing = get_settings().llm_keys_missing()
    checks["llm_keys"] = "ok" if not missing else "missing: " + ", ".join(missing)
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )
