"""Tenders, documents, knowledge base (PRD 10.2). OWNER: ingestion agent."""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile

from app.api.deps import CurrentUser, SessionDep
from app.schemas.tenders_api import (
    DashboardStatsResponse,
    DocumentListResponse,
    DocumentOut,
    DocumentUploadResponse,
    PagePreviewResponse,
    RunSummaryOut,
    TenderCreateRequest,
    TenderDetailResponse,
    TenderListResponse,
    TenderOut,
    TenderResponse,
)
from app.services.document_service import DocumentService, UploadResult
from app.services.tender_service import TenderService

router = APIRouter(tags=["tenders"])

Files = Annotated[list[UploadFile], File(description="PDF or DOCX files")]


def _upload_response(result: UploadResult) -> DocumentUploadResponse:
    return DocumentUploadResponse(
        documents=[DocumentOut.model_validate(d) for d in result.documents],
        warnings=result.warnings,
    )


@router.post("/tenders", response_model=TenderResponse, status_code=201)
async def create_tender(
    user: CurrentUser, session: SessionDep, body: TenderCreateRequest | None = None
) -> TenderResponse:
    tender = await TenderService(session).create(user, body.title if body else None)
    return TenderResponse(tender=TenderOut.model_validate(tender))


@router.get("/tenders", response_model=TenderListResponse)
async def list_tenders(
    user: CurrentUser,
    session: SessionDep,
    status: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TenderListResponse:
    items, total = await TenderService(session).list(user.organisation_id, status, page, page_size)
    return TenderListResponse(items=[TenderOut.model_validate(t) for t in items], total=total)


@router.get("/tenders/{tender_id}", response_model=TenderDetailResponse)
async def get_tender(
    tender_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TenderDetailResponse:
    detail = await TenderService(session).detail(user.organisation_id, tender_id)
    return TenderDetailResponse(
        tender=TenderOut.model_validate(detail.tender),
        documents=[DocumentOut.model_validate(d) for d in detail.documents],
        latest_run=RunSummaryOut.model_validate(detail.latest_run) if detail.latest_run else None,
    )


@router.post(
    "/tenders/{tender_id}/documents", response_model=DocumentUploadResponse, status_code=201
)
async def upload_tender_documents(
    tender_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    files: Files,
    kind: Annotated[str, Form()],
    addendum_seq: Annotated[int | None, Form()] = None,
) -> DocumentUploadResponse:
    result = await DocumentService(session).upload_to_tender(
        user, tender_id, files, kind, addendum_seq
    )
    return _upload_response(result)


@router.post("/knowledge-base/documents", response_model=DocumentUploadResponse, status_code=201)
async def upload_knowledge_base_documents(
    user: CurrentUser,
    session: SessionDep,
    files: Files,
    kind: Annotated[str, Form()],
) -> DocumentUploadResponse:
    result = await DocumentService(session).upload_to_knowledge_base(user, files, kind)
    return _upload_response(result)


@router.get("/knowledge-base/documents", response_model=DocumentListResponse)
async def list_knowledge_base_documents(
    user: CurrentUser, session: SessionDep
) -> DocumentListResponse:
    docs = await DocumentService(session).list_knowledge_base(user.organisation_id)
    return DocumentListResponse(items=[DocumentOut.model_validate(d) for d in docs])


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    await DocumentService(session).delete(user.organisation_id, document_id)
    return Response(status_code=204)


@router.get("/documents/{document_id}/pages/{page_no}", response_model=PagePreviewResponse)
async def get_document_page(
    document_id: uuid.UUID,
    page_no: int,
    user: CurrentUser,
    session: SessionDep,
) -> PagePreviewResponse:
    preview = await DocumentService(session).page_preview(
        user.organisation_id, document_id, page_no
    )
    return PagePreviewResponse(
        document_id=preview.document.id,
        page_no=preview.page.page_no,
        page_count=preview.document.page_count,
        text=preview.page.text,
        tables=preview.page.tables,
        ocr_used=preview.page.ocr_used,
    )


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def dashboard_stats(user: CurrentUser, session: SessionDep) -> DashboardStatsResponse:
    stats = await TenderService(session).dashboard_stats(user.organisation_id)
    return DashboardStatsResponse(
        tenders=stats.tenders, awaiting_review=stats.awaiting_review, approved=stats.approved
    )
