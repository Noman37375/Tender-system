"""ingest node (PRD 7.3): extraction, chunking and embedding via app.ingestion."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.graph.nodes.base import NodeCall, NodeOutput, graph_node
from app.ingestion.pipeline import IngestResult, ingest_document

NAME = "ingest"


class NoUsableTenderDocumentError(RuntimeError):
    pass


async def work(call: NodeCall) -> NodeOutput:
    tender_ids = [uuid.UUID(d) for d in call.state.get("tender_document_ids", [])]
    company_ids = [uuid.UUID(d) for d in call.state.get("company_document_ids", [])]
    all_ids = list(dict.fromkeys(tender_ids + company_ids))
    results: list[IngestResult] = []
    warnings: list[str] = []

    async def persist(session: AsyncSession) -> None:
        # ingest_document commits nothing: page/chunk rows and document status land in the
        # node's single persist transaction, together with the COMPLETED step.
        for done, document_id in enumerate(all_ids, start=1):
            result = await ingest_document(session, call.organisation_id, document_id, call.llm)
            results.append(result)
            warnings.extend(result.warnings)
            if result.extraction_status == "FAILED":
                warnings.append(f"Document {document_id} could not be extracted")
            await call.progress("documents ingested", done, len(all_ids))
        ok_tender = [
            r for r in results if r.document_id in tender_ids and r.extraction_status != "FAILED"
        ]
        if tender_ids and not ok_tender:
            raise NoUsableTenderDocumentError("no tender document could be extracted")

    return NodeOutput(
        state={"warnings": warnings},
        persist=persist,
        output={"documents": len(all_ids)},
        summary=f"{len(all_ids)} documents",
    )


ingest = graph_node(NAME)(work)
