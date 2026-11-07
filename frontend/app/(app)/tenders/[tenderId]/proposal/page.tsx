"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Eye, Loader2, Pencil, RefreshCw, Save, ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Markdown, PlaceholderBadge } from "@/components/markdown";
import { NoRun } from "@/components/no-run";
import { SourceChip } from "@/components/source-preview";
import { SeverityBadge } from "@/components/status";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, InlineError, Loading, cx, focusRing, humanize, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { qk, useLatestRun } from "@/lib/hooks";
import type { AuditFinding, AuditReport, EvidenceItem, ProposalSection, Requirement, Run } from "@/lib/types";

const REGEN_TIMEOUT_MS = 3 * 60_000;

// ---------------------------------------------------------------- SectionNav

function SectionNav({
  sections,
  current,
  onSelect,
  findings,
  dirty,
  regenerating,
}: {
  sections: ProposalSection[];
  current: string;
  onSelect: (key: string) => void;
  findings: AuditFinding[];
  dirty: Set<string>;
  regenerating: Set<string>;
}) {
  return (
    <nav aria-label="Proposal sections">
      <ol className="space-y-0.5">
        {sections.map((s, i) => {
          const issues = findings.filter((f) => f.section_key === s.section_key && f.severity !== "MINOR").length;
          const active = s.section_key === current;
          return (
            <li key={s.section_key}>
              <button
                type="button"
                onClick={() => onSelect(s.section_key)}
                aria-current={active ? "true" : undefined}
                className={cx(
                  "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                  active ? "bg-teal-50 font-medium text-teal-900" : "text-slate-700 hover:bg-slate-100",
                  focusRing,
                )}
              >
                <span className="w-5 shrink-0 text-right text-xs tabular-nums text-slate-400">{i + 1}</span>
                <span className="min-w-0 flex-1">{s.title}</span>
                <span className="flex shrink-0 items-center gap-1">
                  {regenerating.has(s.section_key) && <Loader2 className="size-3.5 animate-spin text-sky-700" aria-label="Regenerating" />}
                  {dirty.has(s.section_key) && <span className="size-2 rounded-full bg-amber-500" title="Unsaved changes" aria-label="Unsaved changes" />}
                  {s.placeholders.length > 0 && (
                    <span className="rounded bg-amber-100 px-1 text-[11px] text-amber-900" title="Client input required">
                      {s.placeholders.length}
                    </span>
                  )}
                  {issues > 0 && (
                    <span className="rounded bg-red-100 px-1 text-[11px] text-red-800" title="Audit issues">
                      {issues}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// ---------------------------------------------------------------- sidebars

function CitationSidebar({
  section,
  evidence,
  reqs,
}: {
  section: ProposalSection;
  evidence: Map<string, EvidenceItem>;
  reqs: Map<string, Requirement>;
}) {
  return (
    <Card title={`Citations (${section.citations.length})`}>
      {section.citations.length === 0 ? (
        <p className="text-sm text-slate-600">This section cites no evidence.</p>
      ) : (
        <ul className="space-y-3 text-sm">
          {section.citations.map((c, i) => (
            <li key={i} className="border-l-2 border-slate-200 pl-3">
              <p className="text-slate-800">{c.claim}</p>
              <div className="mt-1 space-y-1">
                {c.evidence_codes.map((code) => {
                  const ev = evidence.get(code);
                  return (
                    <div key={code} className="flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="font-mono font-semibold text-slate-700">{code}</span>
                      {ev ? (
                        <>
                          <span className="text-slate-600">{ev.description}</span>
                          <SourceChip source={ev.source} />
                        </>
                      ) : (
                        <Badge tone="red">Unknown code</Badge>
                      )}
                    </div>
                  );
                })}
                {c.req_codes.map((code) => (
                  <div key={code} className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="font-mono font-semibold text-slate-700">{code}</span>
                    <span className="text-slate-600">{reqs.get(code)?.description ?? ""}</span>
                  </div>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function PlaceholderList({ section, total }: { section: ProposalSection; total: number }) {
  return (
    <Card title={`Client input needed (${section.placeholders.length})`}>
      {section.placeholders.length === 0 ? (
        <p className="text-sm text-slate-600">Nothing to fill in for this section.</p>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {section.placeholders.map((p, i) => (
            <li key={i}>
              <PlaceholderBadge text={p.replace(/^\[CLIENT INPUT REQUIRED:\s*/, "").replace(/\]$/, "")} />
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-slate-500">{total} placeholder(s) across the whole proposal.</p>
    </Card>
  );
}

function AuditFindingsPanel({ report, sectionKey }: { report: AuditReport | null; sectionKey: string }) {
  if (!report)
    return (
      <Card title="Audit">
        <p className="text-sm text-slate-600">The audit has not run on this version yet.</p>
      </Card>
    );
  const here = report.findings.filter((f) => f.section_key === sectionKey);
  const general = report.findings.filter((f) => !f.section_key);
  const list = (items: AuditFinding[]) => (
    <ul className="space-y-2 text-sm">
      {items.map((f, i) => (
        <li key={i} className="rounded-md border border-slate-200 p-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <SeverityBadge value={f.severity} />
            <span className="text-xs font-medium text-slate-700">{humanize(f.type)}</span>
          </div>
          <p className="mt-1 text-slate-800">{f.description}</p>
          {f.suggested_fix && (
            <p className="mt-1 text-xs text-slate-600">
              <span className="font-medium">Suggested fix:</span> {f.suggested_fix}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
  return (
    <Card
      title="Audit findings"
      actions={
        report.passed ? (
          <Badge tone="green">
            <ShieldCheck className="size-3.5" aria-hidden /> Passed
          </Badge>
        ) : (
          <Badge tone="red">
            <ShieldAlert className="size-3.5" aria-hidden /> Issues found
          </Badge>
        )
      }
    >
      {here.length === 0 ? <p className="text-sm text-slate-600">No findings for this section.</p> : list(here)}
      {general.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-600">Whole proposal</h3>
          {list(general)}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- editor

function RegenerateDialog({
  open,
  onClose,
  section,
  onConfirm,
  busy,
  error,
}: {
  open: boolean;
  onClose: () => void;
  section: ProposalSection;
  onConfirm: (instructions: string) => void;
  busy: boolean;
  error: unknown;
}) {
  const [instructions, setInstructions] = useState("");
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Regenerate "${section.title}"`}
      description="The section is rewritten from the evidence. Your manual edits to this section will be replaced."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={busy} onClick={() => onConfirm(instructions.trim())}>
            <RefreshCw className="size-4" aria-hidden /> Regenerate
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Instructions (optional)" hint="For example: shorten to one page, stress local support capacity.">
          <textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} rows={4} maxLength={2000} className={inputClass} />
        </Field>
        <InlineError error={error} />
      </div>
    </Dialog>
  );
}

function SectionEditor({
  runId,
  section,
  draft,
  setDraft,
  canEdit,
  regenerating,
  onRegenerated,
}: {
  runId: string;
  section: ProposalSection;
  draft: string;
  setDraft: (v: string) => void;
  canEdit: boolean;
  regenerating: boolean;
  onRegenerated: () => void;
}) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [regenOpen, setRegenOpen] = useState(false);
  const dirty = draft !== section.content_md;

  const save = useMutation({
    mutationFn: () => api.saveSection(runId, section.section_key, draft),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.proposal(runId) }),
  });
  const regen = useMutation({
    mutationFn: (instructions: string) => api.regenerateSection(runId, section.section_key, instructions || undefined),
    onSuccess: () => {
      setRegenOpen(false);
      onRegenerated();
    },
  });

  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          {section.title}
          {section.edited_by_user && <Badge tone="blue">Edited by you</Badge>}
          {dirty && <Badge tone="amber">Unsaved</Badge>}
        </span>
      }
      actions={
        <>
          <div role="group" aria-label="View mode" className="flex rounded-md border border-slate-300 p-0.5">
            {(["preview", "edit"] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                disabled={m === "edit" && !canEdit}
                onClick={() => setMode(m)}
                className={cx(
                  "flex items-center gap-1 rounded px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50",
                  mode === m ? "bg-slate-800 text-white" : "text-slate-700 hover:bg-slate-100",
                  focusRing,
                )}
              >
                {m === "preview" ? <Eye className="size-3.5" aria-hidden /> : <Pencil className="size-3.5" aria-hidden />}
                {m === "preview" ? "Preview" : "Edit"}
              </button>
            ))}
          </div>
          {canEdit && (
            <>
              <Button size="sm" disabled={regenerating} onClick={() => setRegenOpen(true)}>
                <RefreshCw className={cx("size-3.5", regenerating && "animate-spin")} aria-hidden />
                {regenerating ? "Regenerating…" : "Regenerate"}
              </Button>
              <Button size="sm" variant="primary" disabled={!dirty} busy={save.isPending} onClick={() => save.mutate()}>
                <Save className="size-3.5" aria-hidden /> Save
              </Button>
            </>
          )}
        </>
      }
    >
      <InlineError error={save.error} />
      {regenerating && (
        <p role="status" className="mb-3 rounded-md bg-sky-50 px-3 py-2 text-sm text-sky-900">
          Regenerating this section. It refreshes here automatically when ready.
        </p>
      )}
      {mode === "edit" && canEdit ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <label className="block">
            <span className="sr-only">Markdown for {section.title}</span>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              spellCheck
              className={cx(inputClass, "min-h-[28rem] font-mono text-[13px] leading-relaxed")}
            />
            <span className="mt-1 block text-xs text-slate-500">
              Markdown. Keep <code>[CLIENT INPUT REQUIRED: …]</code> markers where your team still has to supply details.
            </span>
          </label>
          <div className="max-h-[32rem] overflow-y-auto rounded-md border border-slate-200 p-4" aria-label="Live preview">
            <Markdown source={draft} />
          </div>
        </div>
      ) : draft.trim() ? (
        <Markdown source={draft} />
      ) : (
        <p className="text-sm text-slate-500">This section is empty.</p>
      )}
      <RegenerateDialog
        key={regenOpen ? "open" : "closed"}
        open={regenOpen}
        onClose={() => setRegenOpen(false)}
        section={section}
        onConfirm={(i) => regen.mutate(i)}
        busy={regen.isPending}
        error={regen.error}
      />
    </Card>
  );
}

// ---------------------------------------------------------------- page

function ProposalView({ run }: { run: Run }) {
  const runId = run.id;
  const [regenerating, setRegenerating] = useState<Record<string, { prev: string; since: number }>>({});
  const regenActive = Object.keys(regenerating).length > 0;

  const proposal = useQuery({
    queryKey: qk.proposal(runId),
    queryFn: () => api.proposal(runId),
    refetchInterval: regenActive ? 5000 : false,
  });
  const analysis = useQuery({ queryKey: qk.analysis(runId), queryFn: () => api.analysis(runId) });

  const sections = useMemo(
    () => [...(proposal.data?.sections ?? [])].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0)),
    [proposal.data],
  );
  const [currentKey, setCurrentKey] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const current = sections.find((s) => s.section_key === currentKey) ?? sections[0];

  // Finish "regenerating" once the server content changes (or give up after a timeout).
  useEffect(() => {
    if (!regenActive) return;
    const now = Date.now();
    const done = Object.entries(regenerating).filter(([key, r]) => {
      const s = sections.find((x) => x.section_key === key);
      return (s && s.content_md !== r.prev) || now - r.since > REGEN_TIMEOUT_MS;
    });
    if (done.length) {
      setRegenerating((cur) => {
        const next = { ...cur };
        done.forEach(([k]) => delete next[k]);
        return next;
      });
      setDrafts((cur) => {
        const next = { ...cur };
        done.forEach(([k]) => delete next[k]);
        return next;
      });
    }
  }, [sections, regenerating, regenActive]);

  const evidence = useMemo(() => new Map((analysis.data?.evidence ?? []).map((e) => [e.evidence_code, e])), [analysis.data]);
  const reqs = useMemo(() => new Map((analysis.data?.requirements ?? []).map((r) => [r.req_code, r])), [analysis.data]);
  const dirty = useMemo(
    () => new Set(sections.filter((s) => drafts[s.section_key] !== undefined && drafts[s.section_key] !== s.content_md).map((s) => s.section_key)),
    [sections, drafts],
  );

  useEffect(() => {
    if (dirty.size === 0) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (proposal.isPending) return <Loading label="Loading proposal…" />;
  if (proposal.isError)
    return (
      <ErrorState
        error={proposal.error}
        title="Could not load the proposal"
        onRetry={() => proposal.refetch()}
        notReadyText="The proposal draft appears once the writing step has finished. Follow progress on the Run tab."
      />
    );
  if (!current) return <EmptyState title="The proposal has no sections yet" />;

  const { proposal: meta, audit_report } = proposal.data;
  const canEdit = run.status === "WAITING_REVIEW";
  const totalPlaceholders = sections.reduce((n, s) => n + s.placeholders.length, 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
        <span>
          Version <strong className="text-slate-900">{meta.version}</strong>
        </span>
        <Badge tone={meta.status === "AUDIT_PASSED" || meta.status === "APPROVED" ? "green" : meta.status === "AUDIT_FAILED" ? "red" : "grey"}>
          {humanize(meta.status)}
        </Badge>
        {!canEdit && (
          <span className="flex items-center gap-1">
            <CircleAlert className="size-4" aria-hidden />
            {run.status === "COMPLETED" ? "Approved proposals are read-only." : "Editing opens when the draft is waiting for review."}
          </span>
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-[14rem_minmax(0,1fr)] xl:grid-cols-[14rem_minmax(0,1fr)_20rem]">
        <aside className="lg:sticky lg:top-4 lg:self-start">
          <Card title="Sections" bodyClassName="p-2">
            <SectionNav
              sections={sections}
              current={current.section_key}
              onSelect={setCurrentKey}
              findings={audit_report?.findings ?? []}
              dirty={dirty}
              regenerating={new Set(Object.keys(regenerating))}
            />
          </Card>
        </aside>

        <SectionEditor
          key={current.section_key}
          runId={runId}
          section={current}
          draft={drafts[current.section_key] ?? current.content_md}
          setDraft={(v) => setDrafts((d) => ({ ...d, [current.section_key]: v }))}
          canEdit={canEdit}
          regenerating={!!regenerating[current.section_key]}
          onRegenerated={() =>
            setRegenerating((r) => ({ ...r, [current.section_key]: { prev: current.content_md, since: Date.now() } }))
          }
        />

        <aside className="space-y-4 lg:col-span-2 xl:col-span-1">
          <AuditFindingsPanel report={audit_report} sectionKey={current.section_key} />
          <PlaceholderList section={current} total={totalPlaceholders} />
          <CitationSidebar section={current} evidence={evidence} reqs={reqs} />
        </aside>
      </div>
    </div>
  );
}

export default function ProposalPage() {
  const { tenderId, run } = useLatestRun();
  if (!run) return <NoRun tenderId={tenderId} />;
  return <ProposalView run={run} />;
}
