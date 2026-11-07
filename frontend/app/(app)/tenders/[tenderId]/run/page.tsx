"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertOctagon,
  ArrowRight,
  Check,
  ChevronRight,
  Circle,
  Hourglass,
  Loader2,
  MinusCircle,
  RefreshCw,
  RotateCcw,
  Square,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";
import { NoRun } from "@/components/no-run";
import { RunStatusChip } from "@/components/status";
import { Badge, Button, Card, EmptyState, ErrorState, InlineError, LinkButton, Loading, cx, formatDate, formatUsd, toNumber } from "@/components/ui";
import { api } from "@/lib/api";
import { isActive, qk, useLatestRun } from "@/lib/hooks";
import { NODE_LABEL, PIPELINE, deriveNodes, type NodeStatus, type NodeView } from "@/lib/pipeline";
import { useRunEvents, type StreamState } from "@/lib/sse";
import type { AgentStep, Run, RunEvent } from "@/lib/types";

// ---------------------------------------------------------------- PipelineGraph

const nodeStyle: Record<NodeStatus, { box: string; label: string; Icon: typeof Check }> = {
  pending: { box: "border-slate-200 bg-white text-slate-500", label: "Pending", Icon: Circle },
  running: { box: "border-sky-400 bg-sky-50 text-sky-900 ring-2 ring-sky-200", label: "Running", Icon: Loader2 },
  done: { box: "border-green-300 bg-green-50 text-green-900", label: "Done", Icon: Check },
  failed: { box: "border-red-400 bg-red-50 text-red-900", label: "Failed", Icon: X },
  skipped: { box: "border-slate-200 bg-slate-50 text-slate-500", label: "Skipped", Icon: MinusCircle },
  waiting: { box: "border-amber-400 bg-amber-50 text-amber-950 ring-2 ring-amber-200", label: "Waiting for you", Icon: Hourglass },
};

function PipelineNode({ label, view }: { label: string; view: NodeView }) {
  const s = nodeStyle[view.status];
  return (
    <li className={cx("w-40 rounded-md border px-3 py-2 text-sm", s.box)}>
      <p className="font-medium leading-tight">{label}</p>
      <p className="mt-1 flex items-center gap-1 text-xs">
        <s.Icon className={cx("size-3.5", view.status === "running" && "animate-spin")} aria-hidden />
        {s.label}
        {view.attempt && view.attempt > 1 ? ` · try ${view.attempt}` : ""}
        {view.revision ? ` · rev ${view.revision}` : ""}
      </p>
      {view.progress && view.progress.total > 0 && (
        <div className="mt-1.5">
          <div
            role="progressbar"
            aria-label={`${label} progress`}
            aria-valuemin={0}
            aria-valuemax={view.progress.total}
            aria-valuenow={view.progress.done}
            className="h-1.5 overflow-hidden rounded bg-sky-100"
          >
            <div className="h-full bg-sky-600" style={{ width: `${(100 * view.progress.done) / view.progress.total}%` }} />
          </div>
          <p className="mt-0.5 truncate text-[11px]" title={view.progress.message}>
            {view.progress.done}/{view.progress.total} {view.progress.message}
          </p>
        </div>
      )}
    </li>
  );
}

function PipelineGraph({ nodes }: { nodes: Record<string, NodeView> }) {
  return (
    <div className="overflow-x-auto pb-2">
      <ol className="flex min-w-max items-center gap-1" aria-label="Pipeline steps in order">
        {PIPELINE.map((col, i) => (
          <li key={i} className="flex items-center gap-1">
            <ul className="flex flex-col gap-2" aria-label={col.length > 1 ? "Steps running in parallel" : undefined}>
              {col.map((n) => (
                <PipelineNode key={n.node} label={n.label} view={nodes[n.node] ?? { status: "pending" }} />
              ))}
            </ul>
            {i < PIPELINE.length - 1 && <ChevronRight className="size-4 shrink-0 text-slate-400" aria-hidden />}
          </li>
        ))}
      </ol>
    </div>
  );
}

// ---------------------------------------------------------------- StepLog

function describe(e: RunEvent): string {
  const n = e.node ? (NODE_LABEL[e.node] ?? e.node) : "";
  switch (e.type) {
    case "run.started":
      return "Run started";
    case "node.started":
      return `${n} started${e.payload.attempt > 1 ? ` (attempt ${e.payload.attempt})` : ""}`;
    case "node.progress":
      return `${n}: ${e.payload.message} (${e.payload.done}/${e.payload.total})`;
    case "node.completed":
      return `${n} finished in ${(e.payload.duration_ms / 1000).toFixed(1)} s${e.payload.summary ? ` — ${e.payload.summary}` : ""}`;
    case "node.failed":
      return `${n} failed: ${e.payload.error}${e.payload.will_retry ? " — retrying" : ""}`;
    case "audit.result":
      return e.payload.passed
        ? "Audit passed"
        : `Audit found ${e.payload.blocker_count} blocker(s) and ${e.payload.major_count} major issue(s)`;
    case "run.waiting_review":
      return "Draft ready for human review";
    case "run.completed":
      return "Run completed";
    case "run.failed":
      return `Run failed: ${e.payload.error}`;
  }
}

const eventTone = (e: RunEvent) =>
  e.type === "node.failed" || e.type === "run.failed"
    ? "text-red-800"
    : e.type === "node.completed" || e.type === "run.completed"
      ? "text-green-800"
      : e.type === "run.waiting_review" || (e.type === "audit.result" && !e.payload.passed)
        ? "text-amber-900"
        : "text-slate-700";

function StepLog({ events, steps }: { events: RunEvent[]; steps: AgentStep[] }) {
  if (events.length === 0 && steps.length === 0)
    return <EmptyState title="No activity yet">Steps appear here as soon as the run starts.</EmptyState>;
  return (
    <div className="space-y-4">
      {events.length > 0 && (
        <ol aria-live="polite" aria-label="Live activity" className="max-h-72 space-y-1 overflow-y-auto font-mono text-xs">
          {[...events].reverse().map((e, i) => (
            <li key={e.id ?? `${e.ts}-${i}`} className={cx("flex gap-2", eventTone(e))}>
              <time className="shrink-0 text-slate-500" dateTime={e.ts}>
                {new Date(e.ts).toLocaleTimeString()}
              </time>
              <span>{describe(e)}</span>
            </li>
          ))}
        </ol>
      )}
      {steps.length > 0 && (
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <caption className="sr-only">Recorded steps</caption>
            <thead className="text-left text-slate-600">
              <tr className="border-b border-slate-200">
                <th scope="col" className="py-1.5 pr-3 font-medium">Step</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Status</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Try / rev</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Model</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Tokens in/out</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Cost</th>
                <th scope="col" className="py-1.5 font-medium">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {steps.map((s) => (
                <tr key={s.id}>
                  <td className="py-1.5 pr-3 text-slate-800">{NODE_LABEL[s.node] ?? s.node}</td>
                  <td className="py-1.5 pr-3">
                    <Badge tone={s.status === "COMPLETED" ? "green" : s.status === "FAILED" ? "red" : s.status === "RUNNING" ? "blue" : "grey"}>
                      {s.status.toLowerCase()}
                    </Badge>
                  </td>
                  <td className="py-1.5 pr-3 tabular-nums text-slate-700">
                    {s.attempt} / {s.revision}
                  </td>
                  <td className="py-1.5 pr-3 text-slate-700">{s.model ?? "—"}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-slate-700">
                    {s.tokens_in.toLocaleString()} / {s.tokens_out.toLocaleString()}
                  </td>
                  <td className="py-1.5 pr-3 text-right tabular-nums text-slate-700">{formatUsd(s.cost_usd)}</td>
                  <td className="py-1.5 text-slate-600">{formatDate(s.started_at, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- CostMeter

function CostMeter({ run }: { run: Run }) {
  const cost = toNumber(run.cost_usd);
  const budget = toNumber(run.budget_usd) || 1;
  const pct = Math.min(100, (100 * cost) / budget);
  const tone = pct >= 90 ? "bg-red-600" : pct >= 70 ? "bg-amber-500" : "bg-teal-600";
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="flex items-baseline justify-between">
          <span className="text-2xl font-semibold tabular-nums text-slate-900">{formatUsd(cost)}</span>
          <span className="text-slate-600">of {formatUsd(budget)} budget</span>
        </div>
        <div
          role="meter"
          aria-label="Cost against budget"
          aria-valuemin={0}
          aria-valuemax={budget}
          aria-valuenow={cost}
          aria-valuetext={`${formatUsd(cost)} of ${formatUsd(budget)}`}
          className="mt-2 h-2 overflow-hidden rounded bg-slate-100"
        >
          <div className={cx("h-full", tone)} style={{ width: `${pct}%` }} />
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <dt className="text-slate-600">Tokens in</dt>
          <dd className="font-medium tabular-nums text-slate-900">{run.tokens_in.toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-slate-600">Tokens out</dt>
          <dd className="font-medium tabular-nums text-slate-900">{run.tokens_out.toLocaleString()}</dd>
        </div>
        <div>
          <dt className="text-slate-600">Revisions</dt>
          <dd className="font-medium tabular-nums text-slate-900">{run.revision_count}</dd>
        </div>
        <div>
          <dt className="text-slate-600">Started</dt>
          <dd className="font-medium text-slate-900">{formatDate(run.started_at, true)}</dd>
        </div>
      </dl>
    </div>
  );
}

// ---------------------------------------------------------------- ErrorPanel

function ErrorPanel({ run, steps, tenderId }: { run: Run; steps: AgentStep[]; tenderId: string }) {
  const qc = useQueryClient();
  const retry = useMutation({
    mutationFn: () => api.retryRun(run.id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.run(run.id) });
      void qc.invalidateQueries({ queryKey: qk.tender(tenderId) });
    },
  });
  const failed = steps.filter((s) => s.status === "FAILED");
  const budget = (run.error ?? "").includes("BUDGET_EXCEEDED");
  return (
    <section role="alert" className="rounded-lg border border-red-300 bg-red-50 p-4 text-sm text-red-900">
      <h2 className="flex items-center gap-2 font-semibold">
        <AlertOctagon className="size-5" aria-hidden /> The run stopped with an error
      </h2>
      {run.error && <p className="mt-1">{run.error}</p>}
      {budget && (
        <p className="mt-1">The cost budget for this run was reached. Retrying continues from the last finished step.</p>
      )}
      {failed.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5">
          {failed.map((s) => (
            <li key={s.id}>
              <span className="font-medium">{NODE_LABEL[s.node] ?? s.node}</span> (attempt {s.attempt}): {s.error ?? "no details"}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex items-center gap-3">
        <Button variant="danger" busy={retry.isPending} onClick={() => retry.mutate()}>
          <RotateCcw className="size-4" aria-hidden /> Retry from last checkpoint
        </Button>
        <span className="text-xs text-red-800">Finished steps are not repeated.</span>
      </div>
      <div className="mt-2">
        <InlineError error={retry.error} />
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- connection indicator

function Connection({ state, onReconnect }: { state: StreamState; onReconnect: () => void }) {
  const map: Record<StreamState, { label: string; tone: "green" | "amber" | "grey" | "blue" }> = {
    idle: { label: "Not connected", tone: "grey" },
    connecting: { label: "Connecting…", tone: "blue" },
    live: { label: "Live", tone: "green" },
    reconnecting: { label: "Reconnecting…", tone: "amber" },
    polling: { label: "Live updates unavailable — refreshing every 5 s", tone: "amber" },
    closed: { label: "Run finished", tone: "grey" },
  };
  const m = map[state];
  return (
    <span className="flex items-center gap-2" role="status">
      <Badge tone={m.tone}>
        {state === "live" && <span className="size-1.5 rounded-full bg-green-600" aria-hidden />}
        {m.label}
      </Badge>
      {(state === "polling" || state === "reconnecting") && (
        <Button size="sm" variant="ghost" onClick={onReconnect}>
          <RefreshCw className="size-3.5" aria-hidden /> Reconnect
        </Button>
      )}
    </span>
  );
}

// ---------------------------------------------------------------- page

function RunView({ runId, tenderId }: { runId: string; tenderId: string }) {
  const qc = useQueryClient();
  const runQ = useQuery({ queryKey: qk.run(runId), queryFn: () => api.getRun(runId) });
  const active = isActive(runQ.data?.run.status) || runQ.isPending;

  const onEvent = useCallback(
    (e: RunEvent) => {
      if (e.type === "node.progress") return;
      void qc.invalidateQueries({ queryKey: qk.run(runId) });
      if (e.type.startsWith("run.") || e.type === "audit.result") {
        void qc.invalidateQueries({ queryKey: qk.tender(tenderId) });
        void qc.invalidateQueries({ queryKey: qk.proposal(runId) });
      }
    },
    [qc, runId, tenderId],
  );
  const { events, state, reconnect } = useRunEvents(runId, active, onEvent);

  // Fallback polling (D10): whenever the live stream is not up and the run is still going.
  const polling = active && state !== "live";
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(() => void qc.invalidateQueries({ queryKey: qk.run(runId) }), 5000);
    return () => clearInterval(t);
  }, [polling, qc, runId]);

  const cancel = useMutation({
    mutationFn: () => api.cancelRun(runId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.run(runId) });
      void qc.invalidateQueries({ queryKey: qk.tender(tenderId) });
    },
  });

  const steps = useMemo(() => runQ.data?.steps ?? [], [runQ.data]);
  const nodes = useMemo(() => deriveNodes(runQ.data?.run, steps, events), [runQ.data, steps, events]);

  if (runQ.isPending) return <Loading label="Loading run…" />;
  if (runQ.isError) return <ErrorState error={runQ.error} title="Could not load the run" onRetry={() => runQ.refetch()} />;

  const { run } = runQ.data;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <RunStatusChip status={run.status} />
          {run.current_node && run.status === "RUNNING" && (
            <span className="text-sm text-slate-600">Now: {NODE_LABEL[run.current_node] ?? run.current_node}</span>
          )}
          <Connection state={state} onReconnect={reconnect} />
        </div>
        {isActive(run.status) && run.status !== "WAITING_REVIEW" && (
          <Button
            variant="secondary"
            busy={cancel.isPending}
            onClick={() => {
              if (window.confirm("Cancel this run? Finished results are kept, but the run stops here.")) cancel.mutate();
            }}
          >
            <Square className="size-4" aria-hidden /> Cancel run
          </Button>
        )}
      </div>
      <InlineError error={cancel.error} />

      {run.status === "FAILED" && <ErrorPanel run={run} steps={steps} tenderId={tenderId} />}

      {run.status === "WAITING_REVIEW" && (
        <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <p>
            <span className="font-semibold">The draft is ready for your review.</span> Check the compliance matrix and
            proposal, then approve or request changes.
          </p>
          <LinkButton href={`/tenders/${tenderId}/review`} variant="primary">
            Go to review <ArrowRight className="size-4" aria-hidden />
          </LinkButton>
        </section>
      )}

      {run.status === "COMPLETED" && (
        <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-green-300 bg-green-50 p-4 text-sm text-green-900">
          <p className="font-medium">Approved. The proposal and compliance matrix are ready to export.</p>
          <LinkButton href={`/tenders/${tenderId}/review`}>Export</LinkButton>
        </section>
      )}

      <Card title="Pipeline">
        <PipelineGraph nodes={nodes} />
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card title="Activity" className="lg:col-span-2">
          <StepLog events={events} steps={steps} />
        </Card>
        <Card title="Cost">
          <CostMeter run={run} />
        </Card>
      </div>
    </div>
  );
}

export default function RunPage() {
  const { tenderId, run } = useLatestRun();
  if (!run) return <NoRun tenderId={tenderId} />;
  return <RunView runId={run.id} tenderId={tenderId} />;
}
