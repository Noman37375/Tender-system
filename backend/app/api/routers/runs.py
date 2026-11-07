"""Runs, SSE, review, results, exports (PRD 10.3-10.5). OWNER: graph agent.

SSE authentication: browsers' EventSource cannot send an Authorization header, so
`GET /runs/{run_id}/events` accepts the access token either as `Authorization: Bearer <jwt>` or
as the `?access_token=<jwt>` query parameter. Reconnects send `Last-Event-ID` (header, or the
`?last_event_id=` query parameter) and receive every stored event with a larger id first.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.deps import CurrentUser, SessionDep
from app.db.models import Run, User
from app.errors import ApiError
from app.graph.events import TERMINAL_EVENTS, BusEvent, EventBus
from app.graph.executor import RunExecutor, executor_lifespan, get_executor
from app.repositories.runs import RunRepository
from app.repositories.users import UserRepository
from app.schemas import runs_api as api
from app.schemas.compliance import BidDecision
from app.schemas.solution import SolutionDesign
from app.security.auth import InvalidTokenError, decode_token
from app.services.run_service import RunService

router = APIRouter(tags=["runs"], lifespan=executor_lifespan)

ExecutorDep = Annotated[RunExecutor, Depends(get_executor)]
PING_SECONDS = 15.0
TERMINAL_RUN_STATUSES = ("COMPLETED", "FAILED", "CANCELLED")
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_bearer = HTTPBearer(auto_error=False)


def get_service(session: SessionDep, executor: ExecutorDep) -> RunService:
    return RunService(session, executor)


ServiceDep = Annotated[RunService, Depends(get_service)]


def run_out(run: Run) -> api.RunOut:
    return api.RunOut.model_validate(run)


# ---- PRD 10.3 runs ---------------------------------------------------------------------------
@router.post("/tenders/{tender_id}/runs", status_code=202, response_model=api.StartRunResponse)
async def start_run(
    tender_id: uuid.UUID, body: api.StartRunRequest, user: CurrentUser, service: ServiceDep
) -> api.StartRunResponse:
    run = await service.start_run(user, tender_id, body)
    return api.StartRunResponse(run_id=run.id, status=run.status)


@router.get("/runs/{run_id}", response_model=api.RunDetail)
async def get_run(run_id: uuid.UUID, user: CurrentUser, service: ServiceDep) -> api.RunDetail:
    run, steps = await service.run_detail(user, run_id)
    return api.RunDetail(run=run_out(run), steps=[api.StepOut.model_validate(s) for s in steps])


@router.post("/runs/{run_id}/review", status_code=202, response_model=api.StatusResponse)
async def review_run(
    run_id: uuid.UUID, body: api.ReviewRequest, user: CurrentUser, service: ServiceDep
) -> api.StatusResponse:
    return api.StatusResponse(status=await service.review(user, run_id, body))


@router.post("/runs/{run_id}/retry", status_code=202, response_model=api.StatusResponse)
async def retry_run(
    run_id: uuid.UUID, user: CurrentUser, service: ServiceDep
) -> api.StatusResponse:
    return api.StatusResponse(status=await service.retry(user, run_id))


@router.post("/runs/{run_id}/cancel", response_model=api.StatusResponse)
async def cancel_run(
    run_id: uuid.UUID, user: CurrentUser, service: ServiceDep
) -> api.StatusResponse:
    return api.StatusResponse(status=await service.cancel(user, run_id))


# ---- PRD 10.5 SSE ----------------------------------------------------------------------------
async def get_sse_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    access_token: Annotated[str | None, Query()] = None,
) -> User:
    """Bearer header, or `?access_token=` because EventSource cannot set headers."""
    token = credentials.credentials if credentials is not None else access_token
    if not token:
        raise ApiError(401, "NOT_AUTHENTICATED", "Missing bearer token")
    try:
        claims = decode_token(token, "access")
    except InvalidTokenError as exc:
        raise ApiError(401, "INVALID_TOKEN", str(exc)) from exc
    user = await UserRepository(session).get(claims.organisation_id, claims.user_id)
    if user is None:
        raise ApiError(401, "INVALID_TOKEN", "User no longer exists")
    return user


def format_sse(event: BusEvent) -> str:
    return f"id: {event.id}\nevent: {event.type}\ndata: {json.dumps(event.data())}\n\n"


async def event_stream(
    bus: EventBus,
    organisation_id: uuid.UUID,
    run_id: uuid.UUID,
    last_event_id: int,
    run_finished: bool,
    ping_seconds: float | None = None,
) -> AsyncIterator[str]:
    """Replay stored events after `last_event_id`, then stream live ones.

    Subscribes before replaying so nothing emitted in between is lost; live events already
    replayed are skipped by id. Ends after a terminal event, or right after the replay when the
    run had already finished.
    """
    interval = PING_SECONDS if ping_seconds is None else ping_seconds
    queue = bus.subscribe(run_id)
    try:
        sent = last_event_id
        for event in await bus.replay(organisation_id, run_id, last_event_id):
            yield format_sse(event)
            sent = event.id
            if event.type in TERMINAL_EVENTS:
                return
        if run_finished:
            return
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=interval)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if event.id <= sent:
                continue
            yield format_sse(event)
            sent = event.id
            if event.type in TERMINAL_EVENTS:
                return
    finally:
        bus.unsubscribe(run_id, queue)


def _parse_last_id(*values: str | None) -> int:
    for value in values:
        if value:
            try:
                return max(int(value), 0)
            except ValueError:
                continue
    return 0


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: uuid.UUID,
    session: SessionDep,
    executor: ExecutorDep,
    user: Annotated[User, Depends(get_sse_user)],
    last_event_id_header: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    last_event_id: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    run = await RunRepository(session).get(user.organisation_id, run_id)
    if run is None:
        raise ApiError(404, "RUN_NOT_FOUND", "Run not found")
    finished = run.status in TERMINAL_RUN_STATUSES and not executor.is_executing(run_id)
    await session.close()
    stream = event_stream(
        executor.bus,
        user.organisation_id,
        run_id,
        _parse_last_id(last_event_id_header, last_event_id),
        finished,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---- PRD 10.4 results ------------------------------------------------------------------------
@router.get("/runs/{run_id}/analysis", response_model=api.AnalysisResponse)
async def get_analysis(
    run_id: uuid.UUID, user: CurrentUser, service: ServiceDep
) -> api.AnalysisResponse:
    return await service.analysis(user, run_id)


@router.get("/runs/{run_id}/compliance", response_model=api.ComplianceResponse)
async def get_compliance(
    run_id: uuid.UUID, user: CurrentUser, service: ServiceDep
) -> api.ComplianceResponse:
    return await service.compliance(user, run_id)


@router.get("/runs/{run_id}/bid-decision", response_model=BidDecision)
async def get_bid_decision(
    run_id: uuid.UUID, user: CurrentUser, service: ServiceDep
) -> BidDecision:
    return await service.bid_decision(user, run_id)


@router.get("/runs/{run_id}/missing", response_model=api.MissingListResponse)
async def get_missing(
    run_id: uuid.UUID, user: CurrentUser, service: ServiceDep
) -> api.MissingListResponse:
    return await service.missing(user, run_id)


@router.patch("/missing/{item_id}", response_model=api.MissingItemResponse)
async def patch_missing(
    item_id: uuid.UUID, body: api.MissingPatch, user: CurrentUser, service: ServiceDep
) -> api.MissingItemResponse:
    return api.MissingItemResponse(item=await service.patch_missing(user, item_id, body))


@router.get("/runs/{run_id}/solution", response_model=SolutionDesign)
async def get_solution(run_id: uuid.UUID, user: CurrentUser, service: ServiceDep) -> SolutionDesign:
    return await service.solution(user, run_id)


@router.get("/runs/{run_id}/forms", response_model=api.FormsResponse)
async def get_forms(run_id: uuid.UUID, user: CurrentUser, service: ServiceDep) -> api.FormsResponse:
    return await service.forms(user, run_id)


@router.get("/runs/{run_id}/proposal", response_model=api.ProposalResponse)
async def get_proposal(
    run_id: uuid.UUID, user: CurrentUser, service: ServiceDep
) -> api.ProposalResponse:
    return await service.proposal(user, run_id)


@router.patch("/runs/{run_id}/proposal/sections/{section_key}", response_model=api.SectionResponse)
async def patch_section(
    run_id: uuid.UUID,
    section_key: str,
    body: api.SectionPatch,
    user: CurrentUser,
    service: ServiceDep,
) -> api.SectionResponse:
    return api.SectionResponse(section=await service.patch_section(user, run_id, section_key, body))


@router.post(
    "/runs/{run_id}/proposal/sections/{section_key}/regenerate",
    status_code=202,
    response_model=api.StatusResponse,
)
async def regenerate_section(
    run_id: uuid.UUID,
    section_key: str,
    user: CurrentUser,
    service: ServiceDep,
    body: api.RegenerateRequest | None = None,
) -> api.StatusResponse:
    status = await service.regenerate_section(
        user, run_id, section_key, body or api.RegenerateRequest()
    )
    return api.StatusResponse(status=status)


# ---- exports ---------------------------------------------------------------------------------
@router.get("/runs/{run_id}/export/proposal.docx")
async def export_docx(
    run_id: uuid.UUID,
    user: CurrentUser,
    service: ServiceDep,
    draft: bool = False,
    include_citations: bool = False,
) -> Response:
    content = await service.export_docx(user, run_id, draft, include_citations)
    name = "proposal-draft.docx" if draft else "proposal.docx"
    return Response(
        content,
        media_type=DOCX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/runs/{run_id}/export/compliance.xlsx")
async def export_xlsx(run_id: uuid.UUID, user: CurrentUser, service: ServiceDep) -> Response:
    content = await service.export_xlsx(user, run_id)
    return Response(
        content,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": 'attachment; filename="compliance.xlsx"'},
    )


@router.get("/runs/{run_id}/export/audit.json")
async def export_audit(run_id: uuid.UUID, user: CurrentUser, service: ServiceDep) -> JSONResponse:
    report: dict[str, Any] = await service.export_audit(user, run_id)
    return JSONResponse(
        report, headers={"Content-Disposition": 'attachment; filename="audit.json"'}
    )
