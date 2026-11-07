"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, CheckCircle2, Download, Info, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { NoRun } from "@/components/no-run";
import { Popover } from "@/components/popover";
import { SourceChip } from "@/components/source-preview";
import {
  ComplianceChip,
  RULE_EXPLANATIONS,
  RecommendationBadge,
  SeverityBadge,
  VerificationBadge,
  complianceLabel,
} from "@/components/status";
import { Badge, Button, Card, EmptyState, ErrorState, Field, InlineError, Loading, cx, humanize, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { qk, useLatestRun } from "@/lib/hooks";
import type {
  BidDecision,
  ComplianceRecord,
  ComplianceStatus,
  ComplianceSummary as Summary,
  EvidenceItem,
  MissingItem,
  MissingResponse,
  Requirement,
} from "@/lib/types";

// ---------------------------------------------------------------- BidDecisionBanner

function BidDecisionBanner({ decision, reqs }: { decision: BidDecision; reqs: Map<string, Requirement> }) {
  const style = {
    NO_BID: { box: "border-red-400 bg-red-50 text-red-950", Icon: AlertOctagon, title: "Recommendation: do not bid" },
    BID_WITH_CONDITIONS: {
      box: "border-amber-400 bg-amber-50 text-amber-950",
      Icon: TriangleAlert,
      title: "Recommendation: bid, once the conditions below are met",
    },
    BID: { box: "border-green-400 bg-green-50 text-green-950", Icon: CheckCircle2, title: "Recommendation: bid" },
  }[decision.recommendation];

  return (
    <section
      role={decision.recommendation === "NO_BID" ? "alert" : "region"}
      aria-label="Bid decision"
      className={cx("rounded-lg border-2 p-4 text-sm", style.box)}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <style.Icon className="size-5" aria-hidden /> {style.title}
        </h2>
        <div className="flex items-center gap-2">
          <RecommendationBadge value={decision.recommendation} />
          <Badge tone={decision.eligibility_passed ? "green" : "red"}>
            Eligibility {decision.eligibility_passed ? "passed" : "not passed"}
          </Badge>
          {decision.score != null && <Badge tone="teal">Score {decision.score}</Badge>}
        </div>
      </div>
      {decision.blocking_req_codes.length > 0 && (
        <div className="mt-3">
          <h3 className="font-semibold">Blocking requirements</h3>
          <ul className="mt-1 space-y-1">
            {decision.blocking_req_codes.map((code) => (
              <li key={code} className="flex gap-2">
                <span className="font-mono text-xs font-semibold">{code}</span>
                <span>{reqs.get(code)?.description ?? ""}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {decision.reasons.length > 0 && (
        <div className="mt-3">
          <h3 className="font-semibold">Why</h3>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {decision.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {decision.recommendation === "NO_BID" && (
        <p className="mt-3 text-xs">
          The run continues so you can still review the draft, but submitting is not advised unless the blocking
          requirements are resolved.
        </p>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- ComplianceSummary

function ComplianceSummary({
  summary,
  filter,
  setFilter,
}: {
  summary: Summary;
  filter: ComplianceStatus | "";
  setFilter: (s: ComplianceStatus | "") => void;
}) {
  const items: { status: ComplianceStatus; count: number; cls: string }[] = [
    { status: "COMPLIANT", count: summary.compliant, cls: "border-green-300 text-green-900" },
    { status: "PARTIAL", count: summary.partial, cls: "border-amber-300 text-amber-950" },
    { status: "NON_COMPLIANT", count: summary.non_compliant, cls: "border-red-300 text-red-900" },
    { status: "UNVERIFIED", count: summary.unverified, cls: "border-slate-300 text-slate-800" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" role="group" aria-label="Filter by status">
      {items.map((i) => {
        const active = filter === i.status;
        return (
          <button
            key={i.status}
            type="button"
            aria-pressed={active}
            onClick={() => setFilter(active ? "" : i.status)}
            className={cx(
              "rounded-lg border-2 bg-white p-3 text-left shadow-sm transition-colors hover:bg-slate-50",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700",
              i.cls,
              active && "ring-2 ring-teal-700",
            )}
          >
            <span className="block text-2xl font-semibold tabular-nums">{i.count}</span>
            <span className="text-sm">{complianceLabel(i.status)}</span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- ComplianceTable

function EvidencePopover({ code, ev }: { code: string; ev: EvidenceItem | undefined }) {
  return (
    <Popover
      label={`Evidence ${code}`}
      trigger={code}
      triggerClassName="rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono text-xs text-slate-800 hover:border-teal-700 hover:text-teal-800"
    >
      {ev ? (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono text-xs font-semibold text-slate-700">{ev.evidence_code}</span>
            <VerificationBadge value={ev.verification_status} />
          </div>
          <p className="text-slate-900">{ev.description}</p>
          <p className="text-xs text-slate-600">{humanize(ev.category)}</p>
          {ev.source.quote && (
            <blockquote className="border-l-4 border-amber-400 bg-amber-50 px-2 py-1 text-xs text-slate-800">
              &ldquo;{ev.source.quote}&rdquo;
            </blockquote>
          )}
          <SourceChip source={ev.source} />
        </div>
      ) : (
        <p className="text-slate-600">Details for this evidence item are not available.</p>
      )}
    </Popover>
  );
}

function ComplianceTable({
  records,
  reqs,
  evidence,
  filter,
}: {
  records: ComplianceRecord[];
  reqs: Map<string, Requirement>;
  evidence: Map<string, EvidenceItem>;
  filter: ComplianceStatus | "";
}) {
  const [mandatoryOnly, setMandatoryOnly] = useState(false);
  const [q, setQ] = useState("");
  const rows = records.filter((r) => {
    const req = reqs.get(r.req_code);
    return (
      (!filter || r.status === filter) &&
      (!mandatoryOnly || req?.is_mandatory) &&
      (!q || `${r.req_code} ${req?.description ?? ""} ${r.rationale}`.toLowerCase().includes(q.toLowerCase()))
    );
  });

  return (
    <Card title={`Compliance matrix (${records.length})`} bodyClassName="p-0">
      <div className="flex flex-wrap items-end gap-4 border-b border-slate-200 p-4">
        <div className="w-64">
          <Field label="Search">
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} className={inputClass} placeholder="Code, requirement or rationale" />
          </Field>
        </div>
        <label className="flex items-center gap-2 pb-2 text-sm text-slate-800">
          <input type="checkbox" checked={mandatoryOnly} onChange={(e) => setMandatoryOnly(e.target.checked)} className="accent-teal-700" />
          Mandatory only
        </label>
        {filter && (
          <span className="pb-2 text-sm text-slate-600">
            Showing <strong>{complianceLabel(filter)}</strong> only
          </span>
        )}
      </div>
      {rows.length === 0 ? (
        <div className="p-4">
          <EmptyState title={records.length ? "No records match these filters" : "No compliance records"} />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <caption className="sr-only">Compliance matrix</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">Code</th>
                <th scope="col" className="px-4 py-2 font-medium">Requirement</th>
                <th scope="col" className="px-4 py-2 font-medium">Status</th>
                <th scope="col" className="px-4 py-2 font-medium">Evidence</th>
                <th scope="col" className="px-4 py-2 font-medium">Rule</th>
                <th scope="col" className="px-4 py-2 font-medium">Assessment</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => {
                const req = reqs.get(r.req_code);
                return (
                  <tr key={r.id ?? r.req_code} className="align-top">
                    <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-slate-700">{r.req_code}</td>
                    <td className="max-w-sm px-4 py-2.5 text-slate-800">
                      {req?.description ?? <span className="text-slate-500">—</span>}
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        {req?.is_mandatory && <Badge tone="red">Mandatory</Badge>}
                        {req && <span className="text-xs text-slate-500">{humanize(req.category)}</span>}
                        {req?.source && <SourceChip source={req.source} />}
                      </div>
                    </td>
                    <td className="px-4 py-2.5">
                      <ComplianceChip status={r.status} />
                      {r.llm_proposed_status && r.llm_proposed_status !== r.status && (
                        <p className="mt-1 text-xs text-slate-500">Model proposed: {complianceLabel(r.llm_proposed_status)}</p>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      {r.evidence_codes.length === 0 ? (
                        <span className="text-xs text-slate-500">None cited</span>
                      ) : (
                        <div className="flex max-w-48 flex-wrap gap-1">
                          {r.evidence_codes.map((c) => (
                            <EvidencePopover key={c} code={c} ev={evidence.get(c)} />
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-1 font-mono text-xs text-slate-700" title={RULE_EXPLANATIONS[r.rule_applied] ?? ""}>
                        {r.rule_applied}
                        {RULE_EXPLANATIONS[r.rule_applied] && <Info className="size-3 text-slate-400" aria-hidden />}
                      </span>
                      {RULE_EXPLANATIONS[r.rule_applied] && (
                        <p className="mt-0.5 max-w-44 text-xs text-slate-500">{RULE_EXPLANATIONS[r.rule_applied]}</p>
                      )}
                    </td>
                    <td className="max-w-md px-4 py-2.5 text-slate-800">
                      <p>{r.rationale}</p>
                      {r.gap_description && (
                        <p className="mt-1 text-xs text-slate-700">
                          <span className="font-medium">Gap:</span> {r.gap_description}
                        </p>
                      )}
                      {r.action_required && (
                        <p className="mt-1 text-xs text-amber-900">
                          <span className="font-medium">Action:</span> {r.action_required}
                        </p>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- MissingInfoChecklist

const severityOrder = { BLOCKER: 0, HIGH: 1, MEDIUM: 2, LOW: 3 } as const;

function MissingInfoChecklist({ runId }: { runId: string }) {
  const qc = useQueryClient();
  const missing = useQuery({ queryKey: qk.missing(runId), queryFn: () => api.missing(runId) });

  const toggle = useMutation({
    mutationFn: (v: { item: MissingItem; resolved: boolean }) => api.setMissingResolved(v.item.id, v.resolved),
    onMutate: async ({ item, resolved }) => {
      await qc.cancelQueries({ queryKey: qk.missing(runId) });
      const prev = qc.getQueryData<MissingResponse>(qk.missing(runId));
      qc.setQueryData<MissingResponse>(qk.missing(runId), (d) =>
        d ? { items: d.items.map((i) => (i.id === item.id ? { ...i, resolved } : i)) } : d,
      );
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.missing(runId), ctx.prev);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: qk.missing(runId) }),
  });

  const items = useMemo(
    () => [...(missing.data?.items ?? [])].sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity]),
    [missing.data],
  );
  const open = items.filter((i) => !i.resolved).length;

  return (
    <Card title={`Missing information${missing.data ? ` (${open} open)` : ""}`}>
      {missing.isPending ? (
        <Loading />
      ) : missing.isError ? (
        <ErrorState error={missing.error} title="Could not load the checklist" onRetry={() => missing.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState title="Nothing missing">Every requirement is backed by evidence.</EmptyState>
      ) : (
        <>
          <ul className="divide-y divide-slate-100">
            {items.map((i) => (
              <li key={i.id} className="py-2">
                <label className="flex cursor-pointer items-start gap-3">
                  <input
                    type="checkbox"
                    checked={i.resolved}
                    onChange={(e) => toggle.mutate({ item: i, resolved: e.target.checked })}
                    className="mt-1 accent-teal-700"
                  />
                  <span className="min-w-0 flex-1 text-sm">
                    <span className={cx("font-medium", i.resolved ? "text-slate-500 line-through" : "text-slate-900")}>
                      {i.item}
                    </span>
                    <span className="block text-slate-600">{i.reason}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    {i.req_code && <span className="font-mono text-xs text-slate-600">{i.req_code}</span>}
                    <SeverityBadge value={i.severity} />
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <InlineError error={toggle.error} />
        </>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- page

function ComplianceView({ runId }: { runId: string }) {
  const [filter, setFilter] = useState<ComplianceStatus | "">("");
  const compliance = useQuery({ queryKey: qk.compliance(runId), queryFn: () => api.compliance(runId) });
  const analysis = useQuery({ queryKey: qk.analysis(runId), queryFn: () => api.analysis(runId) });
  const bid = useQuery({ queryKey: qk.bid(runId), queryFn: () => api.bidDecision(runId), retry: false });
  const exportXlsx = useMutation({ mutationFn: () => api.downloadComplianceXlsx(runId) });

  const reqs = useMemo(
    () => new Map((analysis.data?.requirements ?? []).map((r) => [r.req_code, r])),
    [analysis.data],
  );
  const evidence = useMemo(
    () => new Map((analysis.data?.evidence ?? []).map((e) => [e.evidence_code, e])),
    [analysis.data],
  );

  if (compliance.isPending) return <Loading label="Loading compliance…" />;
  if (compliance.isError)
    return (
      <ErrorState
        error={compliance.error}
        title="Could not load the compliance matrix"
        onRetry={() => compliance.refetch()}
        notReadyText="The compliance matrix appears once requirements have been checked against your evidence. Follow progress on the Run tab."
      />
    );

  return (
    <div className="space-y-5">
      {bid.data ? (
        <BidDecisionBanner decision={bid.data} reqs={reqs} />
      ) : bid.isPending ? (
        <Loading label="Loading bid decision…" />
      ) : (
        <ErrorState error={bid.error} title="Could not load the bid decision" onRetry={() => bid.refetch()} notReadyText="The bid decision appears right after the compliance check." />
      )}
      {analysis.isError && (
        <ErrorState error={analysis.error} title="Requirement details could not be loaded" onRetry={() => analysis.refetch()} />
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-900">Compliance summary</h2>
        <Button busy={exportXlsx.isPending} onClick={() => exportXlsx.mutate()}>
          <Download className="size-4" aria-hidden /> Export XLSX
        </Button>
      </div>
      <InlineError error={exportXlsx.error} />
      <ComplianceSummary summary={compliance.data.summary} filter={filter} setFilter={setFilter} />
      <ComplianceTable records={compliance.data.records} reqs={reqs} evidence={evidence} filter={filter} />
      <MissingInfoChecklist runId={runId} />
    </div>
  );
}

export default function CompliancePage() {
  const { tenderId, run } = useLatestRun();
  if (!run) return <NoRun tenderId={tenderId} />;
  return <ComplianceView runId={run.id} />;
}
