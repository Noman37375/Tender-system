// Pure helpers that turn run steps + live SSE events into per-node status for the PipelineGraph.

import type { AgentStep, NodeName, Run, RunEvent } from "./types";

export type NodeStatus = "pending" | "running" | "done" | "failed" | "skipped" | "waiting";

export interface NodeView {
  status: NodeStatus;
  attempt?: number;
  revision?: number;
  progress?: { done: number; total: number; message: string };
  error?: string;
}

/** Graph columns in execution order; nodes in the same column run in parallel (PRD §7.2). */
export const PIPELINE: { node: NodeName; label: string }[][] = [
  [{ node: "ingest", label: "Read documents" }],
  [
    { node: "tender_extract", label: "Tender requirements" },
    { node: "company_extract", label: "Company evidence" },
  ],
  [{ node: "compliance", label: "Compliance check" }],
  [{ node: "bid_decision", label: "Bid decision" }],
  [
    { node: "solution_design", label: "Solution design" },
    { node: "form_detection", label: "Tender forms" },
  ],
  [{ node: "write_sections", label: "Write proposal" }],
  [{ node: "audit", label: "Audit" }],
  [{ node: "human_review", label: "Your review" }],
  [{ node: "finalize", label: "Finalise" }],
];

export const NODE_LABEL: Record<string, string> = Object.fromEntries(
  PIPELINE.flat().map((n) => [n.node, n.label]),
);

const time = (s: string | null | undefined) => (s ? new Date(s).getTime() : 0);

function latestStep(steps: AgentStep[]): AgentStep | undefined {
  return [...steps].sort(
    (a, b) => a.revision - b.revision || a.attempt - b.attempt || time(a.started_at) - time(b.started_at),
  )[steps.length - 1];
}

export function deriveNodes(run: Run | undefined, steps: AgentStep[], events: RunEvent[]): Record<string, NodeView> {
  const out: Record<string, NodeView> = {};
  const lastTouched: Record<string, number> = {};

  for (const { node } of PIPELINE.flat()) {
    const s = latestStep(steps.filter((x) => x.node === node));
    if (!s) {
      out[node] = { status: "pending" };
      lastTouched[node] = 0;
      continue;
    }
    out[node] = {
      status:
        s.status === "RUNNING" ? "running" : s.status === "COMPLETED" ? "done" : s.status === "FAILED" ? "failed" : "skipped",
      attempt: s.attempt,
      revision: s.revision,
      error: s.error ?? undefined,
    };
    lastTouched[node] = Math.max(time(s.started_at), time(s.finished_at));
  }

  // Overlay live events that are newer than what the steps endpoint told us.
  for (const e of events) {
    if (!e.node || !(e.node in out)) continue;
    const t = time(e.ts);
    if (t < lastTouched[e.node]) continue;
    const cur = out[e.node];
    switch (e.type) {
      case "node.started":
        out[e.node] = { status: "running", attempt: e.payload.attempt, revision: cur.revision };
        break;
      case "node.progress":
        out[e.node] = { ...cur, status: "running", progress: e.payload };
        break;
      case "node.completed":
        out[e.node] = { ...cur, status: "done", progress: undefined, error: undefined };
        break;
      case "node.failed":
        out[e.node] = {
          ...cur,
          status: e.payload.will_retry ? "running" : "failed",
          error: e.payload.error,
          attempt: e.payload.attempt,
        };
        break;
    }
    lastTouched[e.node] = t;
  }

  if (run?.status === "WAITING_REVIEW") out.human_review = { ...out.human_review, status: "waiting" };
  if (run?.status === "COMPLETED") {
    out.human_review = { ...out.human_review, status: "done" };
    out.finalize = { ...out.finalize, status: "done" };
  }
  return out;
}
