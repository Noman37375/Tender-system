// Mirrors backend/app/schemas/*.py and the API contract in docs/TECHNICAL_PRD.md §10.
// Keep in sync. Where the PRD is silent the shape chosen here is listed in the
// frontend hand-off notes so the backend can match it.

// ---------------------------------------------------------------- auth (schemas/api.py)

export type Role = "admin" | "bid_manager" | "technical_lead" | "viewer";

export interface User {
  id: string;
  organisation_id: string;
  email: string;
  name: string;
  role: Role;
}

export interface Organisation {
  id: string;
  name: string;
  jurisdiction: string;
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  user: User;
}

export interface MeResponse {
  user: User;
  organisation: Organisation;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: unknown };
}

/** Pydantic serialises Decimal as a JSON string; accept both. */
export type Money = number | string;

// ---------------------------------------------------------------- common (schemas/common.py)

export interface SourceRef {
  document_id: string;
  page: number;
  quote: string;
}

export type Confidence = "HIGH" | "MEDIUM" | "LOW";

// ---------------------------------------------------------------- tenders & documents (§5, §10.2)

export type TenderStatus =
  | "DRAFT"
  | "PROCESSING"
  | "AWAITING_REVIEW"
  | "CHANGES_REQUESTED"
  | "APPROVED"
  | "FAILED";

export interface Tender {
  id: string;
  title: string | null;
  reference_no: string | null;
  procuring_entity: string | null;
  submission_deadline: string | null;
  status: TenderStatus;
  created_at: string;
  updated_at: string | null;
}

export type TenderDocumentKind = "TENDER" | "ADDENDUM";
export type CompanyDocumentKind =
  | "COMPANY_PROFILE"
  | "PROJECT_CREDENTIAL"
  | "CV"
  | "CERTIFICATION"
  | "FINANCIAL_STATEMENT"
  | "OTHER";
export type DocumentKind = TenderDocumentKind | CompanyDocumentKind;
export type ExtractionStatus = "PENDING" | "DONE" | "PARTIAL" | "FAILED";

export interface DocumentOut {
  id: string;
  tender_id: string | null;
  kind: DocumentKind;
  filename: string;
  mime_type: string;
  size_bytes: number;
  page_count: number | null;
  extraction_status: ExtractionStatus;
  addendum_seq: number | null;
  created_at: string;
}

export interface TenderListResponse {
  items: Tender[];
  total: number;
}

export interface TenderDetailResponse {
  tender: Tender;
  documents: DocumentOut[];
  latest_run: Run | null;
}

export interface DocumentsResponse {
  documents: DocumentOut[];
}

export interface DocumentListResponse {
  items: DocumentOut[];
}

/** GET /documents/{id}/pages/{page_no} — mirrors schemas/pages.py PageText. */
export interface PageText {
  document_id: string;
  page_no: number;
  text: string;
  tables: { rows: (string | null)[][] }[];
}

export interface DashboardStats {
  tenders: number;
  awaiting_review: number;
  approved: number;
}

// ---------------------------------------------------------------- runs (§5 runs/agent_steps, §10.3)

export type RunStatus =
  | "PENDING"
  | "RUNNING"
  | "WAITING_REVIEW"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export const TERMINAL_RUN_STATUSES: RunStatus[] = ["COMPLETED", "FAILED", "CANCELLED"];

export type NodeName =
  | "ingest"
  | "tender_extract"
  | "company_extract"
  | "compliance"
  | "bid_decision"
  | "solution_design"
  | "form_detection"
  | "write_sections"
  | "audit"
  | "human_review"
  | "finalize";

export interface Run {
  id: string;
  tender_id: string;
  status: RunStatus;
  current_node: string | null;
  revision_count: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: Money;
  budget_usd: Money;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export type StepStatus = "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED";

export interface AgentStep {
  id: string;
  node: string;
  revision: number;
  attempt: number;
  status: StepStatus;
  prompt_version: string | null;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd: Money;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface RunDetailResponse {
  run: Run;
  steps: AgentStep[];
}

export interface StartRunRequest {
  company_document_ids?: string[];
  use_knowledge_base: boolean;
}

export interface StartRunResponse {
  run_id: string;
  status: RunStatus;
}

export interface StatusResponse {
  status: RunStatus | string;
}

export type ReviewAction = "APPROVE" | "REQUEST_CHANGES";

export interface ReviewRequest {
  action: ReviewAction;
  sections?: string[];
  notes?: string;
}

// ---------------------------------------------------------------- SSE (§10.5)

export interface SsePayloads {
  "run.started": Record<string, never>;
  "node.started": { attempt: number };
  "node.progress": { message: string; done: number; total: number };
  "node.completed": {
    duration_ms: number;
    tokens_in: number;
    tokens_out: number;
    cost_usd: Money;
    summary: string;
  };
  "node.failed": { error: string; attempt: number; will_retry: boolean };
  "audit.result": { passed: boolean; blocker_count: number; major_count: number };
  "run.waiting_review": { audit_passed: boolean };
  "run.completed": Record<string, never>;
  "run.failed": { error: string };
}

export type SseEventType = keyof SsePayloads;

export const SSE_EVENT_TYPES: SseEventType[] = [
  "run.started",
  "node.started",
  "node.progress",
  "node.completed",
  "node.failed",
  "audit.result",
  "run.waiting_review",
  "run.completed",
  "run.failed",
];

export type RunEvent = {
  [K in SseEventType]: {
    /** run_events.id, from the SSE `id:` field (null when unknown). */
    id: string | null;
    type: K;
    run_id: string;
    node: string | null;
    ts: string;
    payload: SsePayloads[K];
  };
}[SseEventType];

// ---------------------------------------------------------------- tender analysis (schemas/tender.py)

export type ReqCategory =
  | "ELIGIBILITY"
  | "FINANCIAL"
  | "EXPERIENCE"
  | "PERSONNEL"
  | "CERTIFICATION"
  | "TECHNICAL"
  | "SUBMISSION"
  | "DELIVERABLE"
  | "EVALUATION"
  | "COMMERCIAL";

export const REQ_CATEGORIES: ReqCategory[] = [
  "ELIGIBILITY",
  "FINANCIAL",
  "EXPERIENCE",
  "PERSONNEL",
  "CERTIFICATION",
  "TECHNICAL",
  "SUBMISSION",
  "DELIVERABLE",
  "EVALUATION",
  "COMMERCIAL",
];

export type CriterionOp = ">=" | "<=" | "==" | "exists" | "count>=";

export interface NumericCriterion {
  metric: string;
  op: CriterionOp;
  value: number;
  unit: string | null;
  window_years: number | null;
  per_item_min_value: number | null;
  qualifier: string | null;
}

export interface Requirement {
  id?: string;
  req_code: string;
  category: ReqCategory;
  description: string;
  is_mandatory: boolean;
  criterion: NumericCriterion | null;
  source: SourceRef | null;
  confidence: Confidence;
}

export interface EvaluationCriterion {
  name: string;
  max_marks: number | null;
  sub_criteria: string[];
  source: SourceRef;
}

export interface TenderMetadata {
  title: string | null;
  reference_no: string | null;
  procuring_entity: string | null;
  submission_deadline: string | null;
  bid_validity_days: number | null;
  bid_security: string | null;
  submission_method: string | null;
  scope_summary: string;
  sources: SourceRef[];
}

// ---------------------------------------------------------------- evidence (schemas/evidence.py)

export type EvidenceCategory =
  | "COMPANY_REGISTRATION"
  | "TAX_REGISTRATION"
  | "FINANCIAL"
  | "PROJECT"
  | "PERSONNEL"
  | "CERTIFICATION"
  | "CAPABILITY"
  | "PARTNERSHIP"
  | "OTHER";

export type VerificationStatus = "DOCUMENTED" | "SELF_DECLARED" | "EXPIRED" | "UNVERIFIED";

export interface EvidenceItem {
  evidence_code: string;
  category: EvidenceCategory;
  description: string;
  attributes: Record<string, unknown>;
  source: SourceRef;
  verification_status: VerificationStatus;
}

export interface AnalysisResponse {
  metadata: TenderMetadata;
  requirements: Requirement[];
  evaluation_criteria: EvaluationCriterion[];
  evidence: EvidenceItem[];
  warnings: string[];
}

// ---------------------------------------------------------------- compliance (schemas/compliance.py)

export type ComplianceStatus = "COMPLIANT" | "PARTIAL" | "NON_COMPLIANT" | "UNVERIFIED";

export interface ComplianceRecord {
  id?: string;
  req_code: string;
  status: ComplianceStatus;
  evidence_codes: string[];
  llm_proposed_status: ComplianceStatus;
  rule_applied: string;
  rationale: string;
  gap_description: string | null;
  action_required: string | null;
}

export interface ComplianceSummary {
  compliant: number;
  partial: number;
  non_compliant: number;
  unverified: number;
}

export interface ComplianceResponse {
  records: ComplianceRecord[];
  summary: ComplianceSummary;
}

export type Recommendation = "BID" | "BID_WITH_CONDITIONS" | "NO_BID";

export interface BidDecision {
  recommendation: Recommendation;
  eligibility_passed: boolean;
  blocking_req_codes: string[];
  reasons: string[];
  score: number | null;
}

export type Severity = "BLOCKER" | "HIGH" | "MEDIUM" | "LOW";

export interface MissingItem {
  id: string;
  item: string;
  reason: string;
  req_code: string | null;
  severity: Severity;
  resolved: boolean;
}

export interface MissingResponse {
  items: MissingItem[];
}

// ---------------------------------------------------------------- solution (schemas/solution.py)

export interface Phase {
  name: string;
  objective: string;
  activities: string[];
  deliverables: string[];
  duration_weeks: number | null;
  dependencies: string[];
}

export interface SolutionDesign {
  approach_summary: string;
  architecture_description: string;
  architecture_components: {
    name?: string;
    purpose?: string;
    technology?: string;
    maps_to_req_codes?: string[];
  }[];
  requirement_traceability: Record<string, string>;
  phases: Phase[];
  testing_strategy: string;
  deployment_strategy: string;
  support_model: string;
  assumptions: string[];
  risks: { risk?: string; impact?: string; mitigation?: string }[];
  capability_gaps: string[];
}

// ---------------------------------------------------------------- forms (schemas/forms.py)

export interface FormField {
  label: string;
  value: string | null;
  evidence_codes: string[];
  status: "FILLED" | "NEEDS_INPUT" | "NOT_APPLICABLE";
}

export type FillStatus = "FILLED" | "PARTIAL" | "EMPTY" | "SKIPPED_FINANCIAL";

export interface TenderForm {
  form_code: string;
  title: string;
  source_page: number | null;
  envelope: "TECHNICAL" | "FINANCIAL" | "ELIGIBILITY";
  fields: FormField[];
  fill_status?: FillStatus;
}

export interface FormsResponse {
  forms: TenderForm[];
}

// ---------------------------------------------------------------- proposal (schemas/proposal.py)

export interface Citation {
  claim: string;
  evidence_codes: string[];
  req_codes: string[];
}

export interface ProposalSection {
  section_key: string;
  title: string;
  content_md: string;
  citations: Citation[];
  placeholders: string[];
  order_index?: number;
  edited_by_user?: boolean;
}

export type ProposalStatus = "DRAFT" | "AUDIT_PASSED" | "AUDIT_FAILED" | "APPROVED";

// ---------------------------------------------------------------- audit (schemas/audit.py)

export type FindingType =
  | "UNSUPPORTED_CLAIM"
  | "MISSING_MANDATORY_COVERAGE"
  | "MISSING_SECTION"
  | "CONTRADICTION"
  | "PRICING_LEAK"
  | "STRUCTURE_DEVIATION"
  | "TERMINOLOGY_INCONSISTENCY"
  | "INVALID_CITATION";

export type FindingSeverity = "BLOCKER" | "MAJOR" | "MINOR";

export interface AuditFinding {
  type: FindingType;
  severity: FindingSeverity;
  section_key: string | null;
  description: string;
  suggested_fix: string;
}

export interface AuditReport {
  passed: boolean;
  findings: AuditFinding[];
  sections_to_revise: string[];
}

export interface ProposalResponse {
  proposal: { version: number; status: ProposalStatus };
  sections: ProposalSection[];
  audit_report: AuditReport | null;
}

export interface SectionResponse {
  section: ProposalSection;
}

export interface MissingItemResponse {
  item: MissingItem;
}
