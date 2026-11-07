"""Domain data read and written by graph nodes and result endpoints (S-01: scoped by org).

Also holds the row -> domain-schema converters used by nodes, services and exports.
"""

import re
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditReport,
    BidDecision,
    ComplianceRecord,
    Document,
    DocumentPage,
    EvidenceItem,
    MissingItem,
    Proposal,
    ProposalSection,
    Requirement,
    Tender,
    TenderForm,
)
from app.schemas import compliance as cs
from app.schemas import evidence as es
from app.schemas import forms as fs
from app.schemas import proposal as ps
from app.schemas import tender as ts
from app.schemas.common import Confidence, SourceRef
from app.schemas.pages import PageText

TENDER_KINDS = ("TENDER", "ADDENDUM")


# ---- converters -----------------------------------------------------------------------------
def _source(document_id: uuid.UUID | None, page: int | None, quote: str | None) -> SourceRef:
    return SourceRef(
        document_id=str(document_id) if document_id else "",
        page=max(page or 1, 1),
        quote=(quote or "")[:500],
    )


def requirement_to_schema(row: Requirement) -> ts.Requirement:
    return ts.Requirement(
        req_code=row.req_code,
        category=ts.ReqCategory(row.category),
        description=row.description,
        is_mandatory=row.is_mandatory,
        criterion=ts.NumericCriterion.model_validate(row.criterion) if row.criterion else None,
        source=_source(row.source_document_id, row.source_page, row.source_quote),
        confidence=Confidence(row.extraction_confidence or "LOW"),
    )


def evidence_to_schema(row: EvidenceItem) -> es.EvidenceItem:
    return es.EvidenceItem(
        evidence_code=row.evidence_code,
        category=es.EvidenceCategory(row.category),
        description=row.description,
        attributes=dict(row.attributes or {}),
        source=_source(row.source_document_id, row.source_page, row.source_quote),
        verification_status=es.VerificationStatus(row.verification_status),
    )


def section_to_schema(row: ProposalSection) -> ps.ProposalSection:
    return ps.ProposalSection(
        section_key=row.section_key,
        title=row.title,
        content_md=row.content_md,
        citations=[ps.Citation.model_validate(c) for c in row.citations or []],
        placeholders=[str(p) for p in row.placeholders or []],
    )


def form_to_schema(row: TenderForm) -> fs.TenderForm:
    return fs.TenderForm(
        form_code=row.form_code,
        title=row.title,
        source_page=max(row.source_page or 1, 1),
        envelope=row.envelope,  # DB check constraint guarantees it
        fields=[fs.FormField.model_validate(f) for f in row.fields or []],
    )


def evidence_code_number(code: str, prefix: str) -> int | None:
    match = re.fullmatch(rf"EV-{re.escape(prefix)}-(\d+)", code)
    return int(match.group(1)) if match else None


class ResultsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- tenders & documents ----------------------------------------------------------------
    async def get_tender(self, organisation_id: uuid.UUID, tender_id: uuid.UUID) -> Tender | None:
        result = await self.session.execute(
            select(Tender).where(Tender.id == tender_id, Tender.organisation_id == organisation_id)
        )
        return result.scalar_one_or_none()

    async def documents(
        self, organisation_id: uuid.UUID, document_ids: Iterable[uuid.UUID]
    ) -> list[Document]:
        ids = list(document_ids)
        if not ids:
            return []
        result = await self.session.execute(
            select(Document).where(
                Document.organisation_id == organisation_id, Document.id.in_(ids)
            )
        )
        return list(result.scalars())

    async def tender_documents(
        self, organisation_id: uuid.UUID, tender_id: uuid.UUID
    ) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(Document.organisation_id == organisation_id, Document.tender_id == tender_id)
            .order_by(Document.created_at)
        )
        return list(result.scalars())

    async def knowledge_base_documents(self, organisation_id: uuid.UUID) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .where(
                Document.organisation_id == organisation_id,
                Document.tender_id.is_(None),
                Document.kind.not_in(TENDER_KINDS),
            )
            .order_by(Document.created_at)
        )
        return list(result.scalars())

    async def pages(self, organisation_id: uuid.UUID, document_id: uuid.UUID) -> list[PageText]:
        result = await self.session.execute(
            select(DocumentPage)
            .where(
                DocumentPage.organisation_id == organisation_id,
                DocumentPage.document_id == document_id,
            )
            .order_by(DocumentPage.page_no)
        )
        return [
            PageText(
                document_id=str(p.document_id), page_no=p.page_no, text=p.text, tables=p.tables
            )
            for p in result.scalars()
        ]

    # ---- requirements -----------------------------------------------------------------------
    async def requirements(
        self, organisation_id: uuid.UUID, tender_id: uuid.UUID, active_only: bool = True
    ) -> list[Requirement]:
        stmt = select(Requirement).where(
            Requirement.organisation_id == organisation_id, Requirement.tender_id == tender_id
        )
        if active_only:
            stmt = stmt.where(Requirement.superseded_by.is_(None))
        result = await self.session.execute(stmt.order_by(Requirement.req_code))
        return list(result.scalars())

    async def requirement_is_referenced(
        self, organisation_id: uuid.UUID, requirement_id: uuid.UUID
    ) -> bool:
        for model, column in (
            (ComplianceRecord, ComplianceRecord.requirement_id),
            (MissingItem, MissingItem.related_requirement_id),
        ):
            result = await self.session.execute(
                select(model.id)
                .where(model.organisation_id == organisation_id, column == requirement_id)
                .limit(1)
            )
            if result.first() is not None:
                return True
        return False

    # ---- evidence ---------------------------------------------------------------------------
    async def evidence_for_documents(
        self, organisation_id: uuid.UUID, document_ids: Iterable[uuid.UUID]
    ) -> list[EvidenceItem]:
        ids = list(document_ids)
        if not ids:
            return []
        result = await self.session.execute(
            select(EvidenceItem)
            .where(
                EvidenceItem.organisation_id == organisation_id,
                EvidenceItem.source_document_id.in_(ids),
            )
            .order_by(EvidenceItem.evidence_code)
        )
        return list(result.scalars())

    async def evidence_ids_by_code(
        self, organisation_id: uuid.UUID, codes: Iterable[str]
    ) -> dict[str, uuid.UUID]:
        wanted = sorted(set(codes))
        if not wanted:
            return {}
        result = await self.session.execute(
            select(EvidenceItem.evidence_code, EvidenceItem.id).where(
                EvidenceItem.organisation_id == organisation_id,
                EvidenceItem.evidence_code.in_(wanted),
            )
        )
        return {code: eid for code, eid in result.tuples()}

    async def lock_evidence_codes(self, organisation_id: uuid.UUID) -> None:
        """Serialise evidence-code assignment per organisation until the transaction ends."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"evidence_codes:{organisation_id}"},
        )

    async def max_evidence_number(self, organisation_id: uuid.UUID, prefix: str) -> int:
        result = await self.session.execute(
            select(EvidenceItem.evidence_code).where(
                EvidenceItem.organisation_id == organisation_id,
                EvidenceItem.evidence_code.like(f"EV-{prefix}-%"),
            )
        )
        numbers = [evidence_code_number(code, prefix) for code in result.scalars()]
        return max((n for n in numbers if n is not None), default=0)

    # ---- compliance / decision / missing ----------------------------------------------------
    async def compliance_records(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[tuple[ComplianceRecord, Requirement]]:
        result = await self.session.execute(
            select(ComplianceRecord, Requirement)
            .join(Requirement, Requirement.id == ComplianceRecord.requirement_id)
            .where(
                ComplianceRecord.organisation_id == organisation_id,
                ComplianceRecord.run_id == run_id,
            )
            .order_by(Requirement.req_code)
        )
        return [(rec, req) for rec, req in result.tuples()]

    async def evidence_codes_by_id(
        self, organisation_id: uuid.UUID, ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        wanted = list(set(ids))
        if not wanted:
            return {}
        result = await self.session.execute(
            select(EvidenceItem.id, EvidenceItem.evidence_code).where(
                EvidenceItem.organisation_id == organisation_id, EvidenceItem.id.in_(wanted)
            )
        )
        return {eid: code for eid, code in result.tuples()}

    async def missing_items(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[tuple[MissingItem, str | None]]:
        result = await self.session.execute(
            select(MissingItem, Requirement.req_code)
            .outerjoin(Requirement, Requirement.id == MissingItem.related_requirement_id)
            .where(MissingItem.organisation_id == organisation_id, MissingItem.run_id == run_id)
            .order_by(MissingItem.created_at)
        )
        return [(item, code) for item, code in result.tuples()]

    async def get_missing_item(
        self, organisation_id: uuid.UUID, item_id: uuid.UUID
    ) -> MissingItem | None:
        result = await self.session.execute(
            select(MissingItem).where(
                MissingItem.id == item_id, MissingItem.organisation_id == organisation_id
            )
        )
        return result.scalar_one_or_none()

    async def bid_decision(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID
    ) -> BidDecision | None:
        result = await self.session.execute(
            select(BidDecision).where(
                BidDecision.organisation_id == organisation_id, BidDecision.run_id == run_id
            )
        )
        return result.scalar_one_or_none()

    async def requirement_codes_by_id(
        self, organisation_id: uuid.UUID, ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        wanted = list(set(ids))
        if not wanted:
            return {}
        result = await self.session.execute(
            select(Requirement.id, Requirement.req_code).where(
                Requirement.organisation_id == organisation_id, Requirement.id.in_(wanted)
            )
        )
        return {rid: code for rid, code in result.tuples()}

    async def delete_run_rows(
        self,
        model: type[ComplianceRecord | MissingItem | BidDecision | TenderForm],
        organisation_id: uuid.UUID,
        run_id: uuid.UUID,
    ) -> None:
        await self.session.execute(
            delete(model).where(model.organisation_id == organisation_id, model.run_id == run_id)
        )

    # ---- proposals --------------------------------------------------------------------------
    async def latest_proposal(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID
    ) -> Proposal | None:
        result = await self.session.execute(
            select(Proposal)
            .where(Proposal.organisation_id == organisation_id, Proposal.run_id == run_id)
            .order_by(Proposal.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def proposal_version(
        self, organisation_id: uuid.UUID, run_id: uuid.UUID, version: int
    ) -> Proposal | None:
        result = await self.session.execute(
            select(Proposal).where(
                Proposal.organisation_id == organisation_id,
                Proposal.run_id == run_id,
                Proposal.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def sections(
        self, organisation_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> list[ProposalSection]:
        result = await self.session.execute(
            select(ProposalSection)
            .where(
                ProposalSection.organisation_id == organisation_id,
                ProposalSection.proposal_id == proposal_id,
            )
            .order_by(ProposalSection.order_index, ProposalSection.section_key)
        )
        return list(result.scalars())

    async def section(
        self, organisation_id: uuid.UUID, proposal_id: uuid.UUID, section_key: str
    ) -> ProposalSection | None:
        result = await self.session.execute(
            select(ProposalSection).where(
                ProposalSection.organisation_id == organisation_id,
                ProposalSection.proposal_id == proposal_id,
                ProposalSection.section_key == section_key,
            )
        )
        return result.scalar_one_or_none()

    async def delete_proposal(self, proposal: Proposal) -> None:
        await self.session.delete(proposal)
        await self.session.flush()

    async def latest_audit(
        self, organisation_id: uuid.UUID, proposal_id: uuid.UUID
    ) -> AuditReport | None:
        result = await self.session.execute(
            select(AuditReport)
            .where(
                AuditReport.organisation_id == organisation_id,
                AuditReport.proposal_id == proposal_id,
            )
            .order_by(AuditReport.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def delete_audits(self, organisation_id: uuid.UUID, proposal_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(AuditReport).where(
                AuditReport.organisation_id == organisation_id,
                AuditReport.proposal_id == proposal_id,
            )
        )

    # ---- forms ------------------------------------------------------------------------------
    async def forms(self, organisation_id: uuid.UUID, run_id: uuid.UUID) -> list[TenderForm]:
        result = await self.session.execute(
            select(TenderForm)
            .where(TenderForm.organisation_id == organisation_id, TenderForm.run_id == run_id)
            .order_by(TenderForm.form_code)
        )
        return list(result.scalars())


def records_to_schema(
    pairs: Sequence[tuple[ComplianceRecord, Requirement]], codes_by_id: dict[uuid.UUID, str]
) -> list[cs.ComplianceRecord]:
    out: list[cs.ComplianceRecord] = []
    for rec, req in pairs:
        out.append(
            cs.ComplianceRecord(
                req_code=req.req_code,
                status=cs.ComplianceStatus(rec.status),
                evidence_codes=[codes_by_id[e] for e in rec.evidence_ids if e in codes_by_id],
                llm_proposed_status=cs.ComplianceStatus(rec.llm_proposed_status or rec.status),
                rule_applied=rec.rule_applied or "",
                rationale=rec.rationale,
                gap_description=rec.gap_description,
                action_required=rec.action_required,
            )
        )
    return out


def missing_to_schema(pairs: Sequence[tuple[MissingItem, str | None]]) -> list[cs.MissingInfo]:
    return [
        cs.MissingInfo(
            item=item.item,
            reason=item.reason,
            req_code=code,
            severity=item.severity,  # DB check constraint
        )
        for item, code in pairs
    ]


def jsonable(value: Any) -> Any:
    """Strip non-JSON values (UUIDs, dates) before writing JSONB."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
