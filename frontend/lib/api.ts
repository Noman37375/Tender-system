// The one typed API client. Every backend call goes through here.
import type {
  AnalysisResponse,
  ApiErrorBody,
  AuthResponse,
  BidDecision,
  CompanyDocumentKind,
  ComplianceResponse,
  DashboardStats,
  DocumentListResponse,
  DocumentsResponse,
  FormsResponse,
  MeResponse,
  MissingItemResponse,
  MissingResponse,
  PageText,
  ProposalResponse,
  ReviewRequest,
  RunDetailResponse,
  SectionResponse,
  SolutionDesign,
  StartRunRequest,
  StartRunResponse,
  StatusResponse,
  Tender,
  TenderDetailResponse,
  TenderDocumentKind,
  TenderListResponse,
  TenderStatus,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const BASE = API_BASE;
const ACCESS = "tenderiq.access";
const REFRESH = "tenderiq.refresh";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

export const tokens = {
  get access() {
    return typeof window === "undefined" ? null : localStorage.getItem(ACCESS);
  },
  get refresh() {
    return typeof window === "undefined" ? null : localStorage.getItem(REFRESH);
  },
  set(access: string, refresh?: string) {
    localStorage.setItem(ACCESS, access);
    if (refresh) localStorage.setItem(REFRESH, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
  },
};

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    return new ApiError(res.status, body.error.code, body.error.message, body.error.details);
  } catch {
    return new ApiError(res.status, "HTTP_ERROR", `Request failed (${res.status})`);
  }
}

let refreshing: Promise<boolean> | null = null;

/** Exchange the refresh token for a new access token. Concurrent callers share one request. */
export function refreshAccess(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const refresh = tokens.refresh;
    if (!refresh) return false;
    try {
      const res = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) return false;
      const { access_token } = (await res.json()) as { access_token: string };
      tokens.set(access_token);
      return true;
    } catch {
      return false;
    }
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

async function send(path: string, init: RequestInit, retry: boolean): Promise<Response> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (tokens.access) headers.set("Authorization", `Bearer ${tokens.access}`);

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (res.status === 401 && retry && (await refreshAccess())) {
    return send(path, init, false);
  }
  if (!res.ok) throw await toError(res);
  return res;
}

async function request<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const res = await send(path, init, retry);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

function uploadForm(files: File[], kind: string, addendumSeq?: number | null): FormData {
  const form = new FormData();
  // FastAPI `files: list[UploadFile]` reads repeated "files" fields.
  for (const f of files) form.append("files", f);
  form.append("kind", kind);
  if (addendumSeq != null) form.append("addendum_seq", String(addendumSeq));
  return form;
}

function filenameFrom(res: Response, fallback: string): string {
  const cd = res.headers.get("Content-Disposition") ?? "";
  const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
  return m ? decodeURIComponent(m[1]) : fallback;
}

/** Fetch a binary with the auth header and hand it to the browser as a download. */
async function download(path: string, fallbackName: string): Promise<void> {
  const res = await send(path, { method: "GET" }, true);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filenameFrom(res, fallbackName);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

const enc = encodeURIComponent;

export const api = {
  // ---- auth & org (§10.1)
  async login(email: string, password: string) {
    const r = await request<AuthResponse>("/auth/login", json("POST", { email, password }), false);
    tokens.set(r.access_token, r.refresh_token);
    return r;
  },
  async register(input: { org_name: string; name: string; email: string; password: string }) {
    const r = await request<AuthResponse>("/auth/register", json("POST", input), false);
    tokens.set(r.access_token, r.refresh_token);
    return r;
  },
  me: () => request<MeResponse>("/me"),
  logout: () => tokens.clear(),

  // ---- dashboard
  dashboardStats: () => request<DashboardStats>("/dashboard/stats"),

  // ---- tenders & documents (§10.2)
  createTender: (title?: string) =>
    request<{ tender: Tender }>("/tenders", json("POST", title ? { title } : {})),
  listTenders: (q: { status?: TenderStatus; page?: number; page_size?: number } = {}) => {
    const p = new URLSearchParams();
    if (q.status) p.set("status", q.status);
    if (q.page) p.set("page", String(q.page));
    if (q.page_size) p.set("page_size", String(q.page_size));
    const qs = p.toString();
    return request<TenderListResponse>(`/tenders${qs ? `?${qs}` : ""}`);
  },
  getTender: (tenderId: string) => request<TenderDetailResponse>(`/tenders/${enc(tenderId)}`),
  uploadTenderDocuments: (
    tenderId: string,
    files: File[],
    kind: TenderDocumentKind,
    addendumSeq?: number | null,
  ) =>
    request<DocumentsResponse>(`/tenders/${enc(tenderId)}/documents`, {
      method: "POST",
      body: uploadForm(files, kind, kind === "ADDENDUM" ? addendumSeq : null),
    }),
  uploadKnowledgeBase: (files: File[], kind: CompanyDocumentKind) =>
    request<DocumentsResponse>("/knowledge-base/documents", {
      method: "POST",
      body: uploadForm(files, kind),
    }),
  listKnowledgeBase: () => request<DocumentListResponse>("/knowledge-base/documents"),
  deleteDocument: (documentId: string) =>
    request<void>(`/documents/${enc(documentId)}`, { method: "DELETE" }),
  getPage: (documentId: string, pageNo: number) =>
    request<PageText>(`/documents/${enc(documentId)}/pages/${pageNo}`),

  // ---- runs (§10.3)
  startRun: (tenderId: string, body: StartRunRequest) =>
    request<StartRunResponse>(`/tenders/${enc(tenderId)}/runs`, json("POST", body)),
  getRun: (runId: string) => request<RunDetailResponse>(`/runs/${enc(runId)}`),
  review: (runId: string, body: ReviewRequest) =>
    request<StatusResponse>(`/runs/${enc(runId)}/review`, json("POST", body)),
  retryRun: (runId: string) => request<StatusResponse>(`/runs/${enc(runId)}/retry`, json("POST")),
  cancelRun: (runId: string) => request<StatusResponse>(`/runs/${enc(runId)}/cancel`, json("POST")),
  /** URL for EventSource (§10.5). EventSource cannot send headers, so the token rides in the query. */
  runEventsUrl: (runId: string, lastEventId?: string | null) => {
    const p = new URLSearchParams();
    if (tokens.access) p.set("access_token", tokens.access);
    if (lastEventId) p.set("last_event_id", lastEventId);
    return `${BASE}/runs/${enc(runId)}/events?${p.toString()}`;
  },

  // ---- results (§10.4)
  analysis: (runId: string) => request<AnalysisResponse>(`/runs/${enc(runId)}/analysis`),
  compliance: (runId: string) => request<ComplianceResponse>(`/runs/${enc(runId)}/compliance`),
  bidDecision: (runId: string) => request<BidDecision>(`/runs/${enc(runId)}/bid-decision`),
  missing: (runId: string) => request<MissingResponse>(`/runs/${enc(runId)}/missing`),
  setMissingResolved: (itemId: string, resolved: boolean) =>
    request<MissingItemResponse>(`/missing/${enc(itemId)}`, json("PATCH", { resolved })),
  solution: (runId: string) => request<SolutionDesign>(`/runs/${enc(runId)}/solution`),
  forms: (runId: string) => request<FormsResponse>(`/runs/${enc(runId)}/forms`),
  proposal: (runId: string) => request<ProposalResponse>(`/runs/${enc(runId)}/proposal`),
  saveSection: (runId: string, sectionKey: string, contentMd: string) =>
    request<SectionResponse>(
      `/runs/${enc(runId)}/proposal/sections/${enc(sectionKey)}`,
      json("PATCH", { content_md: contentMd }),
    ),
  regenerateSection: (runId: string, sectionKey: string, instructions?: string) =>
    request<StatusResponse | undefined>(
      `/runs/${enc(runId)}/proposal/sections/${enc(sectionKey)}/regenerate`,
      json("POST", instructions ? { instructions } : {}),
    ),

  // ---- exports (§10.4, §12)
  downloadProposalDocx: (runId: string, opts: { draft?: boolean } = {}) =>
    download(
      `/runs/${enc(runId)}/export/proposal.docx${opts.draft ? "?draft=true" : ""}`,
      opts.draft ? "proposal-DRAFT.docx" : "proposal.docx",
    ),
  downloadComplianceXlsx: (runId: string) =>
    download(`/runs/${enc(runId)}/export/compliance.xlsx`, "compliance.xlsx"),
  downloadAuditJson: (runId: string) =>
    download(`/runs/${enc(runId)}/export/audit.json`, "audit.json"),
};

/** Human-readable message for any thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message || "Something went wrong";
  return "Could not reach the server";
}
