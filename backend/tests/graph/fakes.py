"""Fakes for the agent / rules / ingestion / export contracts the graph calls.

The graph only orchestrates; these fakes stand in for the business logic so graph and API tests
are deterministic and independent of the other modules' implementations.
"""

import re
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Document, DocumentPage, Organisation, Tender, User
from app.graph.events import EventBus
from app.graph.executor import RunExecutor
from app.graph.nodes import (
    audit as audit_node,
)
from app.graph.nodes import (
    company_extract as company_node,
)
from app.graph.nodes import (
    compliance as compliance_node,
)
from app.graph.nodes import (
    ingest as ingest_node,
)
from app.ingestion.pipeline import IngestResult
from app.llm.adapter import BudgetExceededError, CallUsage
from app.llm.fake import FakeLLMClient
from app.schemas.audit import AuditFinding, AuditReport, FindingType
from app.schemas.common import Confidence, SourceRef
from app.schemas.compliance import (
    BidDecision,
    ComplianceRecord,
    ComplianceStatus,
    LLMMatch,
    MissingInfo,
)
from app.schemas.evidence import (
    CompanyEvidence,
    EvidenceCategory,
    EvidenceItem,
    VerificationStatus,
)
from app.schemas.forms import FormField, TenderForm
from app.schemas.proposal import ProposalSection
from app.schemas.solution import SolutionDesign
from app.schemas.tender import (
    AddendumChanges,
    ReqCategory,
    Requirement,
    TenderMetadata,
    TenderRequirements,
)

SRC = SourceRef(document_id="00000000-0000-0000-0000-000000000000", page=1, quote="quote")


class CostingFakeLLM(FakeLLMClient):
    """FakeLLMClient that exposes the node's CallUsage so fakes can simulate spend."""

    def __init__(self, usage: CallUsage) -> None:
        super().__init__()
        self.usage = usage


def req(code: str, category: ReqCategory, mandatory: bool = True) -> Requirement:
    return Requirement(
        req_code=code,
        category=category,
        description=f"Requirement {code}",
        is_mandatory=mandatory,
        source=SRC,
        confidence=Confidence.HIGH,
    )


@dataclass
class Scenario:
    calls: Counter[str] = field(default_factory=Counter)
    recommendation: str = "BID"
    audit_passes: deque[bool] = field(default_factory=deque)  # default: pass
    fail_once: set[str] = field(default_factory=set)
    cost_per_ingest: Decimal = Decimal("0")
    budget_error_in: str | None = None
    written: list[list[str]] = field(default_factory=list)
    instructions: list[str | None] = field(default_factory=list)
    findings_seen: list[dict[str, Any] | None] = field(default_factory=list)
    drop_match_for: str | None = None
    with_addendum_changes: bool = False

    def hit(self, name: str) -> None:
        self.calls[name] += 1
        if name in self.fail_once:
            self.fail_once.discard(name)
            raise RuntimeError(f"simulated failure in {name}")
        if self.budget_error_in == name:
            raise BudgetExceededError("adapter refused the next call")

    # ---- ingestion ----------------------------------------------------------------------------
    async def ingest_document(
        self, session: AsyncSession, organisation_id: uuid.UUID, document_id: uuid.UUID, llm: Any
    ) -> IngestResult:
        self.hit("ingest")
        if self.cost_per_ingest and isinstance(llm, CostingFakeLLM):
            llm.usage.cost_usd += self.cost_per_ingest
            llm.usage.tokens_in += 100
        return IngestResult(document_id, 1, "DONE", [])

    # ---- tender -------------------------------------------------------------------------------
    async def extract_tender(self, llm: Any, pages: Any, run_id: str) -> TenderRequirements:
        self.hit("tender_extract")
        return TenderRequirements(
            metadata=TenderMetadata(
                title="Smart City Network",
                reference_no="PPRA-42",
                procuring_entity="City Authority",
                submission_deadline="2030-01-01",
                scope_summary="Build a network",
            ),
            requirements=[
                req("ELG-001", ReqCategory.ELIGIBILITY),
                req("EXP-001", ReqCategory.EXPERIENCE, mandatory=False),
                req("TEC-001", ReqCategory.TECHNICAL),
            ],
            extraction_warnings=["page 3 table unreadable"],
        )

    async def apply_addendum(
        self, llm: Any, current: TenderRequirements, pages: Any, run_id: str
    ) -> AddendumChanges:
        self.hit("apply_addendum")
        if not self.with_addendum_changes:
            return AddendumChanges()
        modified = req("TEC-001", ReqCategory.TECHNICAL).model_copy(
            update={"description": "Requirement TEC-001 (amended)"}
        )
        return AddendumChanges(
            modified=[modified],
            added=[req("TBD", ReqCategory.DELIVERABLE)],
            deleted_req_codes=["EXP-001"],
            metadata_changes={"submission_deadline": "2030-02-01"},
        )

    # ---- company ------------------------------------------------------------------------------
    async def extract_company_document(
        self, llm: Any, kind: str, pages: Any, run_id: str
    ) -> CompanyEvidence:
        self.hit("company_extract")
        return CompanyEvidence(
            company_name="Acme Networks",
            items=[
                EvidenceItem(
                    evidence_code="TBD",
                    category=EvidenceCategory.PROJECT,
                    description=f"Project from {kind}",
                    attributes={"client": "City", "value": 100},
                    source=SRC,
                    verification_status=VerificationStatus.DOCUMENTED,
                ),
                EvidenceItem(
                    evidence_code="TBD",
                    category=EvidenceCategory.CERTIFICATION,
                    description="ISO 27001",
                    attributes={"name": "ISO 27001", "expiry_date": "2029-06-30"},
                    source=SRC,
                    verification_status=VerificationStatus.EXPIRED,
                ),
            ],
        )

    @staticmethod
    def effective_status(
        item: EvidenceItem, tender_deadline: date | None, today: date
    ) -> VerificationStatus:
        expiry = item.attributes.get("expiry_date")
        if item.category is EvidenceCategory.CERTIFICATION and expiry:
            expires = date.fromisoformat(expiry)
            if expires < today or (tender_deadline is not None and expires < tender_deadline):
                return VerificationStatus.EXPIRED
        return item.verification_status

    # ---- compliance ---------------------------------------------------------------------------
    async def select_candidates(
        self, llm: Any, requirements: list[Requirement], evidence: list[EvidenceItem], k: int = 8
    ) -> dict[str, list[EvidenceItem]]:
        return {r.req_code: evidence for r in requirements}

    async def match_requirements(
        self,
        llm: Any,
        candidates: dict[str, list[EvidenceItem]],
        requirements: list[Requirement],
        run_id: str,
    ) -> list[LLMMatch]:
        self.hit("compliance")
        out: list[LLMMatch] = []
        for r in requirements:
            if r.req_code == self.drop_match_for:
                continue
            codes = [e.evidence_code for e in candidates[r.req_code][:1]]
            status = (
                ComplianceStatus.NON_COMPLIANT
                if self.recommendation == "NO_BID" and r.req_code == "ELG-001"
                else ComplianceStatus.COMPLIANT
            )
            out.append(
                LLMMatch(
                    req_code=r.req_code,
                    proposed_status=status,
                    confidence=Confidence.HIGH,
                    evidence_codes=codes,
                    rationale="matched",
                )
            )
        return out

    @staticmethod
    def apply_rules(
        match: LLMMatch,
        requirement: Requirement,
        evidence_by_code: dict[str, EvidenceItem],
        tender_deadline: date | None,
    ) -> tuple[ComplianceRecord, list[str]]:
        codes = [c for c in match.evidence_codes if c in evidence_by_code]
        record = ComplianceRecord(
            req_code=match.req_code,
            status=match.proposed_status if codes else ComplianceStatus.UNVERIFIED,
            evidence_codes=codes,
            llm_proposed_status=match.proposed_status,
            rule_applied="R6" if codes else "R2",
            rationale=match.rationale,
        )
        return record, []

    # ---- decision -----------------------------------------------------------------------------
    @staticmethod
    def decide(requirements: list[Requirement], records: list[ComplianceRecord]) -> BidDecision:
        blocking = [
            r.req_code for r in records if r.status is ComplianceStatus.NON_COMPLIANT
        ]
        return BidDecision(
            recommendation="NO_BID" if blocking else "BID",
            eligibility_passed=not blocking,
            blocking_req_codes=blocking,
            reasons=["rule reason"],
            score=None,
        )

    @staticmethod
    def missing_items(
        requirements: list[Requirement], records: list[ComplianceRecord]
    ) -> list[MissingInfo]:
        return [
            MissingInfo(
                item=f"Evidence for {r.req_code}",
                reason=r.rationale,
                req_code=r.req_code,
                severity="BLOCKER",
            )
            for r in records
            if r.status is not ComplianceStatus.COMPLIANT
        ]

    async def explain(
        self, llm: Any, decision: BidDecision, records: list[ComplianceRecord], run_id: str
    ) -> list[str]:
        return [f"Recommendation is {decision.recommendation}"]

    # ---- solution / forms ---------------------------------------------------------------------
    async def design_solution(
        self,
        llm: Any,
        requirements: list[Requirement],
        evidence: list[EvidenceItem],
        scope_summary: str,
        run_id: str,
    ) -> SolutionDesign:
        self.hit("solution_design")
        return SolutionDesign(
            approach_summary="Approach",
            architecture_description="Arch",
            architecture_components=[],
            requirement_traceability={"TEC-001": "covered"},
            phases=[],
            testing_strategy="t",
            deployment_strategy="d",
            support_model="s",
            assumptions=[],
            risks=[],
            capability_gaps=[],
        )

    async def detect_forms(
        self, llm: Any, pages: Any, evidence: list[EvidenceItem], run_id: str
    ) -> list[TenderForm]:
        self.hit("form_detection")
        return [
            TenderForm(
                form_code="FORM-1",
                title="Bid Form",
                source_page=2,
                envelope="TECHNICAL",
                fields=[
                    FormField(label="Company name", value="Acme", status="FILLED"),
                    FormField(label="Signature", status="NEEDS_INPUT"),
                ],
            ),
            TenderForm(
                form_code="FORM-2",
                title="Price Schedule",
                source_page=9,
                envelope="FINANCIAL",
                fields=[FormField(label="Total price", value="PKR 1", status="FILLED")],
            ),
        ]

    # ---- writing / audit ----------------------------------------------------------------------
    async def write_sections(
        self,
        llm: Any,
        section_keys: list[str],
        ctx: Any,
        run_id: str,
        findings_by_section: dict[str, list[AuditFinding]] | None = None,
        user_instructions: str | None = None,
        concurrency: int = 4,
    ) -> dict[str, ProposalSection]:
        self.hit("write_sections")
        n = len(self.written) + 1
        self.written.append(list(section_keys))
        self.instructions.append(user_instructions)
        self.findings_seen.append(
            {k: len(v) for k, v in findings_by_section.items()} if findings_by_section else None
        )
        return {
            k: ProposalSection(
                section_key=k,
                title=k.replace("_", " ").title(),
                content_md=f"{k} pass {n} [CLIENT INPUT REQUIRED: x]",
                citations=[],
                placeholders=["[CLIENT INPUT REQUIRED: x]"],
            )
            for k in section_keys
        }

    async def write_section(
        self,
        llm: Any,
        section_key: str,
        title: str,
        ctx: Any,
        run_id: str,
        findings: Any = None,
        user_instructions: str | None = None,
    ) -> ProposalSection:
        self.hit("write_section")
        return ProposalSection(
            section_key=section_key,
            title=title,
            content_md=f"regenerated {section_key}: {user_instructions}",
            citations=[],
            placeholders=[],
        )

    @staticmethod
    def deterministic_audit(*args: Any, **kwargs: Any) -> list[AuditFinding]:
        return []

    async def review(
        self,
        llm: Any,
        sections: dict[str, ProposalSection],
        requirements: list[Requirement],
        evidence: list[EvidenceItem],
        automated: list[AuditFinding],
        run_id: str,
    ) -> list[AuditFinding]:
        self.hit("audit")
        passed = self.audit_passes.popleft() if self.audit_passes else True
        if passed:
            return []
        return [
            AuditFinding(
                type=FindingType.UNSUPPORTED_CLAIM,
                severity="MAJOR",
                section_key="experience",
                description="claim without citation",
                suggested_fix="cite evidence",
            )
        ]

    @staticmethod
    def build_report(findings: list[AuditFinding]) -> AuditReport:
        bad = [f for f in findings if f.severity in ("BLOCKER", "MAJOR")]
        return AuditReport(
            passed=not bad,
            findings=findings,
            sections_to_revise=sorted({f.section_key for f in bad if f.section_key}),
        )

    @staticmethod
    def extract_placeholders(content_md: str) -> list[str]:
        return re.findall(r"\[CLIENT INPUT REQUIRED:[^\]]*\]", content_md)

    @staticmethod
    def build_proposal_docx(**kwargs: Any) -> bytes:
        return b"DOCX-DRAFT" if kwargs["draft"] else b"DOCX-FINAL"

    @staticmethod
    def build_compliance_xlsx(**kwargs: Any) -> bytes:
        return b"XLSX:" + str(len(kwargs["records"])).encode()


def install(monkeypatch: pytest.MonkeyPatch, sc: Scenario) -> None:
    from app.agents import (
        auditor,
        bid_reasons,
        company_extractor,
        compliance_matcher,
        form_detector,
        section_writer,
        solution_designer,
        tender_extractor,
    )
    from app.rules import bid_decision
    from app.services import run_service

    monkeypatch.setattr(ingest_node, "ingest_document", sc.ingest_document)
    monkeypatch.setattr(tender_extractor, "extract_tender", sc.extract_tender)
    monkeypatch.setattr(tender_extractor, "apply_addendum", sc.apply_addendum)
    monkeypatch.setattr(company_extractor, "extract_company_document", sc.extract_company_document)
    monkeypatch.setattr(company_node, "effective_status", sc.effective_status)
    monkeypatch.setattr(compliance_matcher, "select_candidates", sc.select_candidates)
    monkeypatch.setattr(compliance_matcher, "match_requirements", sc.match_requirements)
    monkeypatch.setattr(compliance_node, "apply_rules", sc.apply_rules)
    monkeypatch.setattr(bid_decision, "decide", sc.decide)
    monkeypatch.setattr(bid_decision, "missing_items", sc.missing_items)
    monkeypatch.setattr(bid_reasons, "explain", sc.explain)
    monkeypatch.setattr(solution_designer, "design_solution", sc.design_solution)
    monkeypatch.setattr(form_detector, "detect_forms", sc.detect_forms)
    monkeypatch.setattr(section_writer, "write_sections", sc.write_sections)
    monkeypatch.setattr(section_writer, "write_section", sc.write_section)
    monkeypatch.setattr(audit_node, "deterministic_audit", sc.deterministic_audit)
    monkeypatch.setattr(auditor, "review", sc.review)
    monkeypatch.setattr(auditor, "build_report", sc.build_report)
    monkeypatch.setattr(run_service, "extract_placeholders", sc.extract_placeholders)
    monkeypatch.setattr(run_service, "build_proposal_docx", sc.build_proposal_docx)
    monkeypatch.setattr(run_service, "build_compliance_xlsx", sc.build_compliance_xlsx)


def llm_factory(usage: CallUsage, budget_usd: Decimal, spent_usd: Decimal) -> CostingFakeLLM:
    return CostingFakeLLM(usage)


def make_executor(
    sessionmaker: async_sessionmaker[AsyncSession], checkpointer: Any
) -> RunExecutor:
    return RunExecutor(
        sessionmaker=sessionmaker,
        bus=EventBus(sessionmaker),
        checkpointer=checkpointer,
        llm_factory=llm_factory,
        max_auto_revisions=1,
        llm_concurrency=2,
    )


@dataclass
class Seeded:
    org_id: uuid.UUID
    user_id: uuid.UUID
    tender_id: uuid.UUID
    tender_doc_ids: list[uuid.UUID]
    company_doc_ids: list[uuid.UUID]


def _doc(org: uuid.UUID, tender: uuid.UUID | None, kind: str, seq: int | None = None) -> Document:
    return Document(
        id=uuid.uuid4(),
        organisation_id=org,
        tender_id=tender,
        kind=kind,
        filename=f"{kind.lower()}.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        sha256="0" * 64,
        storage_path="/tmp/x",
        extraction_status="DONE",
        addendum_seq=seq,
    )


async def seed(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    org_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    with_addendum: bool = False,
) -> Seeded:
    async with sessionmaker() as session, session.begin():
        if org_id is None:
            org = Organisation(id=uuid.uuid4(), name="Acme")
            session.add(org)
            await session.flush()
            org_id = org.id
        if user_id is None:
            user = User(
                id=uuid.uuid4(),
                organisation_id=org_id,
                email=f"{uuid.uuid4().hex}@example.com",
                name="U",
                password_hash="x",
                role="admin",
            )
            session.add(user)
            await session.flush()
            user_id = user.id
        tender = Tender(id=uuid.uuid4(), organisation_id=org_id, status="DRAFT", created_by=user_id)
        session.add(tender)
        await session.flush()
        tender_docs = [_doc(org_id, tender.id, "TENDER")]
        if with_addendum:
            tender_docs.append(_doc(org_id, tender.id, "ADDENDUM", seq=1))
        company_docs = [_doc(org_id, None, "COMPANY_PROFILE"), _doc(org_id, None, "CERTIFICATION")]
        session.add_all(tender_docs + company_docs)
        await session.flush()
        session.add(
            DocumentPage(
                organisation_id=org_id,
                document_id=tender_docs[0].id,
                page_no=1,
                text="Tender page",
                char_count=11,
            )
        )
    return Seeded(
        org_id, user_id, tender.id, [d.id for d in tender_docs], [d.id for d in company_docs]
    )


# ---- driving runs through the service layer ------------------------------------------------------
async def load_user(sessionmaker: async_sessionmaker[AsyncSession], seeded: Seeded) -> User:
    async with sessionmaker() as session:
        user = await session.get(User, seeded.user_id)
        assert user is not None
        return user


async def start_run(executor: RunExecutor, seeded: Seeded, *, wait: bool = True) -> uuid.UUID:
    from app.schemas.runs_api import StartRunRequest
    from app.services.run_service import RunService

    user = await load_user(executor.sessionmaker, seeded)
    async with executor.sessionmaker() as session:
        run = await RunService(session, executor).start_run(
            user, seeded.tender_id, StartRunRequest(use_knowledge_base=True)
        )
        run_id = run.id
    if wait:
        await executor.wait(run_id)
    return run_id


async def review_run(
    executor: RunExecutor,
    seeded: Seeded,
    run_id: uuid.UUID,
    action: str,
    sections: list[str] | None = None,
    notes: str | None = None,
) -> None:
    from app.schemas.runs_api import ReviewRequest
    from app.services.run_service import RunService

    user = await load_user(executor.sessionmaker, seeded)
    async with executor.sessionmaker() as session:
        await RunService(session, executor).review(
            user,
            run_id,
            ReviewRequest(action=action, sections=sections, notes=notes),  # type: ignore[arg-type]
        )
    await executor.wait(run_id)


async def retry_run(executor: RunExecutor, seeded: Seeded, run_id: uuid.UUID) -> None:
    from app.services.run_service import RunService

    user = await load_user(executor.sessionmaker, seeded)
    async with executor.sessionmaker() as session:
        await RunService(session, executor).retry(user, run_id)
    await executor.wait(run_id)
