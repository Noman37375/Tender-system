"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useMemo, useState } from "react";
import { NoRun } from "@/components/no-run";
import { SourceChip } from "@/components/source-preview";
import { ConfidenceBadge, VerificationBadge } from "@/components/status";
import { Badge, Card, EmptyState, ErrorState, Field, Loading, formatDate, humanize, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { qk, useLatestRun } from "@/lib/hooks";
import { REQ_CATEGORIES, type AnalysisResponse, type Confidence, type NumericCriterion, type ReqCategory } from "@/lib/types";

function MetadataCard({ data }: { data: AnalysisResponse }) {
  const m = data.metadata;
  const rows: [string, string | null | undefined][] = [
    ["Reference", m.reference_no],
    ["Procuring entity", m.procuring_entity],
    ["Submission deadline", m.submission_deadline ? formatDate(m.submission_deadline, true) : null],
    ["Bid validity", m.bid_validity_days != null ? `${m.bid_validity_days} days` : null],
    ["Bid security", m.bid_security],
    ["Submission method", m.submission_method],
  ];
  return (
    <Card title={m.title || "Tender overview"}>
      <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt className="text-slate-600">{k}</dt>
            <dd className="font-medium text-slate-900">{v || <span className="font-normal text-slate-400">Not stated</span>}</dd>
          </div>
        ))}
      </dl>
      {m.scope_summary && (
        <div className="mt-4">
          <h3 className="text-sm font-medium text-slate-600">Scope</h3>
          <p className="mt-1 text-sm leading-relaxed text-slate-800">{m.scope_summary}</p>
        </div>
      )}
      {m.sources.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
          Sources:
          {m.sources.map((s, i) => (
            <SourceChip key={i} source={s} />
          ))}
        </div>
      )}
    </Card>
  );
}

function criterionText(c: NumericCriterion) {
  const parts = [`${humanize(c.metric)} ${c.op} ${c.value.toLocaleString()}${c.unit ? ` ${c.unit}` : ""}`];
  if (c.window_years) parts.push(`within ${c.window_years} years`);
  if (c.per_item_min_value) parts.push(`each ≥ ${c.per_item_min_value.toLocaleString()}`);
  if (c.qualifier) parts.push(c.qualifier);
  return parts.join(", ");
}

function RequirementsTable({ data }: { data: AnalysisResponse }) {
  const [category, setCategory] = useState<ReqCategory | "">("");
  const [mandatory, setMandatory] = useState<"" | "yes" | "no">("");
  const [confidence, setConfidence] = useState<Confidence | "">("");
  const [q, setQ] = useState("");

  const rows = useMemo(
    () =>
      data.requirements.filter(
        (r) =>
          (!category || r.category === category) &&
          (!mandatory || r.is_mandatory === (mandatory === "yes")) &&
          (!confidence || r.confidence === confidence) &&
          (!q || `${r.req_code} ${r.description}`.toLowerCase().includes(q.toLowerCase())),
      ),
    [data.requirements, category, mandatory, confidence, q],
  );

  return (
    <Card title={`Requirements (${data.requirements.length})`} bodyClassName="p-0">
      <div className="grid gap-3 border-b border-slate-200 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Search">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Code or text" className={inputClass} />
        </Field>
        <Field label="Category">
          <select value={category} onChange={(e) => setCategory(e.target.value as ReqCategory | "")} className={inputClass}>
            <option value="">All categories</option>
            {REQ_CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {humanize(c)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Mandatory">
          <select value={mandatory} onChange={(e) => setMandatory(e.target.value as "" | "yes" | "no")} className={inputClass}>
            <option value="">All</option>
            <option value="yes">Mandatory only</option>
            <option value="no">Optional only</option>
          </select>
        </Field>
        <Field label="Confidence">
          <select value={confidence} onChange={(e) => setConfidence(e.target.value as Confidence | "")} className={inputClass}>
            <option value="">All</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low (check the source)</option>
          </select>
        </Field>
      </div>
      {rows.length === 0 ? (
        <div className="p-4">
          <EmptyState title={data.requirements.length ? "No requirements match these filters" : "No requirements were extracted"} />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <caption className="sr-only">Tender requirements</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">Code</th>
                <th scope="col" className="px-4 py-2 font-medium">Requirement</th>
                <th scope="col" className="px-4 py-2 font-medium">Category</th>
                <th scope="col" className="px-4 py-2 font-medium">Mandatory</th>
                <th scope="col" className="px-4 py-2 font-medium">Confidence</th>
                <th scope="col" className="px-4 py-2 font-medium">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.req_code} className="align-top">
                  <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-slate-700">{r.req_code}</td>
                  <td className="px-4 py-2.5 text-slate-800">
                    {r.description}
                    {r.criterion && (
                      <p className="mt-1 text-xs text-slate-600">
                        <span className="font-medium">Criterion:</span> {criterionText(r.criterion)}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-slate-700">{humanize(r.category)}</td>
                  <td className="px-4 py-2.5">
                    {r.is_mandatory ? <Badge tone="red">Mandatory</Badge> : <span className="text-slate-500">Optional</span>}
                  </td>
                  <td className="px-4 py-2.5">
                    <ConfidenceBadge value={r.confidence} />
                  </td>
                  <td className="px-4 py-2.5">
                    <SourceChip source={r.source} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function EvaluationCriteria({ data }: { data: AnalysisResponse }) {
  if (data.evaluation_criteria.length === 0) return null;
  return (
    <Card title="Evaluation criteria">
      <ul className="divide-y divide-slate-100 text-sm">
        {data.evaluation_criteria.map((c, i) => (
          <li key={i} className="flex flex-wrap items-start justify-between gap-2 py-2">
            <div>
              <p className="font-medium text-slate-900">{c.name}</p>
              {c.sub_criteria.length > 0 && (
                <ul className="mt-1 list-disc pl-5 text-slate-700">
                  {c.sub_criteria.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              )}
            </div>
            <div className="flex items-center gap-2">
              {c.max_marks != null && <Badge tone="teal">{c.max_marks} marks</Badge>}
              <SourceChip source={c.source} />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function EvidenceRegister({ data }: { data: AnalysisResponse }) {
  return (
    <Card title={`Company evidence (${data.evidence.length})`} bodyClassName="p-0">
      {data.evidence.length === 0 ? (
        <div className="p-4">
          <EmptyState title="No company evidence">No company documents were used, or nothing could be extracted from them.</EmptyState>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <caption className="sr-only">Company evidence register</caption>
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium">Code</th>
                <th scope="col" className="px-4 py-2 font-medium">Evidence</th>
                <th scope="col" className="px-4 py-2 font-medium">Category</th>
                <th scope="col" className="px-4 py-2 font-medium">Proof</th>
                <th scope="col" className="px-4 py-2 font-medium">Source</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.evidence.map((e) => (
                <tr key={e.evidence_code} className="align-top">
                  <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs text-slate-700">{e.evidence_code}</td>
                  <td className="px-4 py-2.5 text-slate-800">{e.description}</td>
                  <td className="px-4 py-2.5 text-slate-700">{humanize(e.category)}</td>
                  <td className="px-4 py-2.5">
                    <VerificationBadge value={e.verification_status} />
                  </td>
                  <td className="px-4 py-2.5">
                    <SourceChip source={e.source} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default function AnalysisPage() {
  const { tenderId, run } = useLatestRun();
  const analysis = useQuery({
    queryKey: qk.analysis(run?.id ?? ""),
    queryFn: () => api.analysis(run!.id),
    enabled: !!run,
  });

  if (!run) return <NoRun tenderId={tenderId} />;
  if (analysis.isPending) return <Loading label="Loading analysis…" />;
  if (analysis.isError)
    return (
      <ErrorState
        error={analysis.error}
        title="Could not load the analysis"
        onRetry={() => analysis.refetch()}
        notReadyText="Requirements appear once the tender has been read. Follow progress on the Run tab."
      />
    );

  const data = analysis.data;
  return (
    <div className="space-y-5">
      {data.warnings.length > 0 && (
        <section className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <h2 className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="size-4" aria-hidden /> Extraction warnings ({data.warnings.length})
          </h2>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {data.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </section>
      )}
      <MetadataCard data={data} />
      <RequirementsTable data={data} />
      <EvaluationCriteria data={data} />
      <EvidenceRegister data={data} />
    </div>
  );
}
