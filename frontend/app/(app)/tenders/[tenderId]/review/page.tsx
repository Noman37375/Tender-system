"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileJson, FileSpreadsheet, FileText, MessageSquareWarning, ShieldAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { NoRun } from "@/components/no-run";
import { RecommendationBadge, SeverityBadge } from "@/components/status";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, InlineError, Loading, humanize, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { qk, useLatestRun } from "@/lib/hooks";
import type { AuditReport, BidDecision, MissingItem, ProposalResponse, Run } from "@/lib/types";

// ---------------------------------------------------------------- AuditSummary

function AuditSummary({
  proposal,
  bid,
  missing,
}: {
  proposal: ProposalResponse;
  bid: BidDecision | undefined;
  missing: MissingItem[] | undefined;
}) {
  const report: AuditReport | null = proposal.audit_report;
  const count = (sev: string) => report?.findings.filter((f) => f.severity === sev).length ?? 0;
  const placeholders = proposal.sections.reduce((n, s) => n + s.placeholders.length, 0);
  const openBlockers = missing?.filter((m) => !m.resolved && m.severity === "BLOCKER").length;
  const titles = new Map(proposal.sections.map((s) => [s.section_key, s.title]));

  return (
    <Card
      title="Audit summary"
      actions={
        report ? (
          report.passed ? (
            <Badge tone="green">
              <ShieldCheck className="size-3.5" aria-hidden /> Audit passed
            </Badge>
          ) : (
            <Badge tone="red">
              <ShieldAlert className="size-3.5" aria-hidden /> Audit found issues
            </Badge>
          )
        ) : (
          <Badge>Not audited</Badge>
        )
      }
    >
      <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
        {[
          ["Blockers", count("BLOCKER"), count("BLOCKER") > 0 ? "text-red-800" : "text-slate-900"],
          ["Major", count("MAJOR"), count("MAJOR") > 0 ? "text-amber-900" : "text-slate-900"],
          ["Minor", count("MINOR"), "text-slate-900"],
          ["Placeholders", placeholders, placeholders > 0 ? "text-amber-900" : "text-slate-900"],
          ["Open blocker items", openBlockers ?? "—", openBlockers ? "text-red-800" : "text-slate-900"],
          ["Sections", proposal.sections.length, "text-slate-900"],
        ].map(([label, value, cls]) => (
          <div key={label as string}>
            <dt className="text-slate-600">{label}</dt>
            <dd className={`text-2xl font-semibold tabular-nums ${cls}`}>{value}</dd>
          </div>
        ))}
      </dl>
      {bid && (
        <p className="mt-4 flex flex-wrap items-center gap-2 text-sm text-slate-700">
          Bid recommendation: <RecommendationBadge value={bid.recommendation} />
          {bid.recommendation === "NO_BID" && (
            <span className="text-red-800">Blocking: {bid.blocking_req_codes.join(", ") || "see Compliance tab"}</span>
          )}
        </p>
      )}
      {report && report.sections_to_revise.length > 0 && (
        <p className="mt-2 text-sm text-slate-700">
          Sections flagged for revision:{" "}
          {report.sections_to_revise.map((k) => titles.get(k) ?? k).join(", ")}
        </p>
      )}
      {report && report.findings.length > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer font-medium text-teal-800">Show all {report.findings.length} findings</summary>
          <ul className="mt-2 space-y-2">
            {report.findings.map((f, i) => (
              <li key={i} className="rounded-md border border-slate-200 p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge value={f.severity} />
                  <span className="text-xs font-medium text-slate-700">{humanize(f.type)}</span>
                  {f.section_key && <span className="text-xs text-slate-500">{titles.get(f.section_key) ?? f.section_key}</span>}
                </div>
                <p className="mt-1 text-slate-800">{f.description}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- dialogs

function ApproveDialog({
  open,
  onClose,
  run,
  warnings,
}: {
  open: boolean;
  onClose: () => void;
  run: Run;
  warnings: string[];
}) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [ack, setAck] = useState(false);
  const approve = useMutation({
    mutationFn: () => api.review(run.id, { action: "APPROVE", ...(notes.trim() ? { notes: notes.trim() } : {}) }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.tender(run.tender_id) });
      void qc.invalidateQueries({ queryKey: qk.run(run.id) });
      void qc.invalidateQueries({ queryKey: qk.proposal(run.id) });
      onClose();
    },
  });
  const needsAck = warnings.length > 0;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Approve this proposal"
      description="Approval finalises the run and unlocks the final DOCX export. Nothing is submitted to the procuring entity."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={approve.isPending} disabled={needsAck && !ack} onClick={() => approve.mutate()}>
            <CheckCircle2 className="size-4" aria-hidden /> Approve
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {needsAck && (
          <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
            <p className="font-medium">Before you approve:</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5">
              {warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
            <label className="mt-2 flex items-center gap-2">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="accent-teal-700" />
              I have read these and want to approve anyway.
            </label>
          </div>
        )}
        <Field label="Notes (optional)">
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} maxLength={4000} className={inputClass} />
        </Field>
        <InlineError error={approve.error} />
      </div>
    </Dialog>
  );
}

function RequestChangesDialog({
  open,
  onClose,
  run,
  proposal,
}: {
  open: boolean;
  onClose: () => void;
  run: Run;
  proposal: ProposalResponse;
}) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(() => new Set(proposal.audit_report?.sections_to_revise ?? []));
  const [notes, setNotes] = useState("");
  const request = useMutation({
    mutationFn: () =>
      api.review(run.id, { action: "REQUEST_CHANGES", sections: [...selected], notes: notes.trim() }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.tender(run.tender_id) });
      void qc.invalidateQueries({ queryKey: qk.run(run.id) });
      onClose();
    },
  });
  const toggle = (k: string) => {
    const next = new Set(selected);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    setSelected(next);
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Request changes"
      description="The selected sections are rewritten with your notes, audited again, and come back to you for review."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            busy={request.isPending}
            disabled={selected.size === 0 || !notes.trim()}
            onClick={() => request.mutate()}
          >
            <MessageSquareWarning className="size-4" aria-hidden /> Send back for changes
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <fieldset>
          <legend className="text-sm font-medium text-slate-800">Sections to rewrite ({selected.size} selected)</legend>
          <ul className="mt-2 max-h-60 space-y-1 overflow-y-auto rounded-md border border-slate-200 p-2 text-sm">
            {proposal.sections.map((s) => (
              <li key={s.section_key}>
                <label className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-slate-50">
                  <input type="checkbox" checked={selected.has(s.section_key)} onChange={() => toggle(s.section_key)} className="accent-teal-700" />
                  {s.title}
                  {proposal.audit_report?.sections_to_revise.includes(s.section_key) && <Badge tone="red">Flagged</Badge>}
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
        <Field label="What should change?" hint="Required. Be specific: the writer only sees these notes and the evidence.">
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4} required maxLength={4000} className={inputClass} />
        </Field>
        <InlineError error={request.error} />
      </div>
    </Dialog>
  );
}

// ---------------------------------------------------------------- exports

function ExportPanel({ run, hasProposal }: { run: Run; hasProposal: boolean }) {
  const completed = run.status === "COMPLETED";
  const docx = useMutation({ mutationFn: () => api.downloadProposalDocx(run.id) });
  const draft = useMutation({ mutationFn: () => api.downloadProposalDocx(run.id, { draft: true }) });
  const xlsx = useMutation({ mutationFn: () => api.downloadComplianceXlsx(run.id) });
  const audit = useMutation({ mutationFn: () => api.downloadAuditJson(run.id) });
  const err = docx.error ?? draft.error ?? xlsx.error ?? audit.error;

  return (
    <Card title="Export">
      <div className="space-y-4 text-sm">
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            disabled={!completed}
            busy={docx.isPending}
            onClick={() => docx.mutate()}
            aria-describedby="docx-hint"
          >
            <FileText className="size-4" aria-hidden /> Proposal (DOCX)
          </Button>
          <Button disabled={!hasProposal} busy={draft.isPending} onClick={() => draft.mutate()}>
            <Download className="size-4" aria-hidden /> Download draft
          </Button>
          <Button busy={xlsx.isPending} onClick={() => xlsx.mutate()}>
            <FileSpreadsheet className="size-4" aria-hidden /> Compliance matrix (XLSX)
          </Button>
          <Button variant="ghost" disabled={!hasProposal} busy={audit.isPending} onClick={() => audit.mutate()}>
            <FileJson className="size-4" aria-hidden /> Audit report (JSON)
          </Button>
        </div>
        <p id="docx-hint" className="text-slate-600">
          {completed
            ? "The proposal is approved. The final DOCX has no watermark."
            : "The final DOCX unlocks after approval. The draft is watermarked “DRAFT — NOT FOR SUBMISSION”."}
        </p>
        <InlineError error={err} />
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------- page

function ReviewView({ run }: { run: Run }) {
  const [dialog, setDialog] = useState<"approve" | "changes" | null>(null);
  const proposal = useQuery({ queryKey: qk.proposal(run.id), queryFn: () => api.proposal(run.id) });
  const bid = useQuery({ queryKey: qk.bid(run.id), queryFn: () => api.bidDecision(run.id), retry: false });
  const missing = useQuery({ queryKey: qk.missing(run.id), queryFn: () => api.missing(run.id), retry: false });

  const waiting = run.status === "WAITING_REVIEW";

  const warnings: string[] = [];
  if (proposal.data?.audit_report && !proposal.data.audit_report.passed) warnings.push("The audit found unresolved issues.");
  if (bid.data?.recommendation === "NO_BID") warnings.push("The bid recommendation is NO BID.");
  const openBlockers = missing.data?.items.filter((m) => !m.resolved && m.severity === "BLOCKER").length ?? 0;
  if (openBlockers) warnings.push(`${openBlockers} blocker item(s) in the missing-information checklist are not resolved.`);
  const placeholders = proposal.data?.sections.reduce((n, s) => n + s.placeholders.length, 0) ?? 0;
  if (placeholders) warnings.push(`${placeholders} placeholder(s) still need client input.`);

  return (
    <div className="space-y-5">
      <Card title="Decision">
        {waiting ? (
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-700">
              Read the proposal and the compliance matrix, then approve or send sections back with notes.
            </p>
            <div className="flex gap-2">
              <Button disabled={!proposal.data} onClick={() => setDialog("changes")}>
                <MessageSquareWarning className="size-4" aria-hidden /> Request changes
              </Button>
              <Button variant="primary" disabled={!proposal.data} onClick={() => setDialog("approve")}>
                <CheckCircle2 className="size-4" aria-hidden /> Approve
              </Button>
            </div>
          </div>
        ) : run.status === "COMPLETED" ? (
          <p className="flex items-center gap-2 text-sm text-green-900">
            <CheckCircle2 className="size-4" aria-hidden /> This proposal has been approved.
          </p>
        ) : (
          <p className="text-sm text-slate-600">
            {run.status === "RUNNING" || run.status === "PENDING"
              ? "The run is still working. Review opens when the draft is ready."
              : run.status === "FAILED"
                ? "The run failed. Retry it from the Run tab."
                : "This run was cancelled."}
          </p>
        )}
      </Card>

      {proposal.isPending ? (
        <Loading label="Loading audit…" />
      ) : proposal.isError ? (
        <ErrorState
          error={proposal.error}
          title="Could not load the proposal"
          onRetry={() => proposal.refetch()}
          notReadyText="The audit summary appears once the proposal has been written and audited."
        />
      ) : proposal.data.sections.length === 0 ? (
        <EmptyState title="No proposal sections yet" />
      ) : (
        <AuditSummary proposal={proposal.data} bid={bid.data} missing={missing.data?.items} />
      )}

      <ExportPanel run={run} hasProposal={!!proposal.data} />

      {proposal.data && (
        <>
          <ApproveDialog key={`a-${dialog === "approve"}`} open={dialog === "approve"} onClose={() => setDialog(null)} run={run} warnings={warnings} />
          <RequestChangesDialog
            key={`c-${dialog === "changes"}`}
            open={dialog === "changes"}
            onClose={() => setDialog(null)}
            run={run}
            proposal={proposal.data}
          />
        </>
      )}
    </div>
  );
}

export default function ReviewPage() {
  const { tenderId, run } = useLatestRun();
  if (!run) return <NoRun tenderId={tenderId} />;
  return <ReviewView run={run} />;
}
