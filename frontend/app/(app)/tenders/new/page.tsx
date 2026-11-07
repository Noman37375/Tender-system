"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Play, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { FileDrop } from "@/components/file-drop";
import { Badge, Button, Card, EmptyState, ErrorState, Field, InlineError, Loading, cx, focusRing, formatBytes, humanize, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { qk } from "@/lib/hooks";
import type { CompanyDocumentKind, DocumentOut, TenderDocumentKind } from "@/lib/types";

const COMPANY_KINDS: { value: CompanyDocumentKind; label: string }[] = [
  { value: "COMPANY_PROFILE", label: "Company profile" },
  { value: "PROJECT_CREDENTIAL", label: "Project credential / completion letter" },
  { value: "CV", label: "CV" },
  { value: "CERTIFICATION", label: "Certification" },
  { value: "FINANCIAL_STATEMENT", label: "Financial statement" },
  { value: "OTHER", label: "Other" },
];

const MAX_TENDER_FILES = 30;

function StepHeading({ n, title, done }: { n: number; title: string; done?: boolean }) {
  return (
    <span className="flex items-center gap-2">
      <span
        className={cx(
          "flex size-6 items-center justify-center rounded-full text-xs font-semibold",
          done ? "bg-teal-700 text-white" : "bg-slate-200 text-slate-700",
        )}
        aria-hidden
      >
        {done ? <CheckCircle2 className="size-4" /> : n}
      </span>
      {title}
    </span>
  );
}

function DocList({ docs, onDelete }: { docs: DocumentOut[]; onDelete?: (d: DocumentOut) => void }) {
  return (
    <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 text-sm">
      {docs.map((d) => (
        <li key={d.id} className="flex items-center justify-between gap-2 px-3 py-2">
          <span className="min-w-0">
            <span className="block truncate font-medium text-slate-800">{d.filename}</span>
            <span className="text-xs text-slate-500">
              {formatBytes(d.size_bytes)}
              {d.page_count != null && ` · ${d.page_count} pages`}
            </span>
          </span>
          <span className="flex items-center gap-2">
            <Badge tone={d.kind === "ADDENDUM" ? "amber" : "teal"}>
              {d.kind === "ADDENDUM" ? `Addendum ${d.addendum_seq ?? ""}`.trim() : humanize(d.kind)}
            </Badge>
            {onDelete && (
              <button
                type="button"
                onClick={() => onDelete(d)}
                className={cx("rounded p-1 text-slate-500 hover:bg-red-50 hover:text-red-700", focusRing)}
                aria-label={`Delete ${d.filename}`}
              >
                <Trash2 className="size-4" aria-hidden />
              </button>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

function TenderUploadZone({ tenderId, docs }: { tenderId: string; docs: DocumentOut[] }) {
  const qc = useQueryClient();
  const [files, setFiles] = useState<File[]>([]);
  const [kind, setKind] = useState<TenderDocumentKind>("TENDER");
  const nextSeq = Math.max(0, ...docs.filter((d) => d.kind === "ADDENDUM").map((d) => d.addendum_seq ?? 0)) + 1;
  const [seq, setSeq] = useState<string>("");
  const seqValue = seq === "" ? nextSeq : Number(seq);

  const upload = useMutation({
    mutationFn: () => api.uploadTenderDocuments(tenderId, files, kind, kind === "ADDENDUM" ? seqValue : null),
    onSuccess: () => {
      setFiles([]);
      setSeq("");
      void qc.invalidateQueries({ queryKey: qk.tender(tenderId) });
    },
  });
  const del = useMutation({
    mutationFn: (d: DocumentOut) => api.deleteDocument(d.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.tender(tenderId) }),
  });

  return (
    <div className="space-y-4">
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-slate-800">Document type</legend>
        <div className="flex flex-wrap gap-4 text-sm text-slate-800">
          {(["TENDER", "ADDENDUM"] as const).map((k) => (
            <label key={k} className="flex items-center gap-2">
              <input type="radio" name="tender-kind" checked={kind === k} onChange={() => setKind(k)} className="accent-teal-700" />
              {k === "TENDER" ? "Tender document" : "Addendum / corrigendum"}
            </label>
          ))}
        </div>
      </fieldset>
      {kind === "ADDENDUM" && (
        <div className="max-w-48">
          <Field label="Addendum number" hint="Addenda are applied in this order.">
            <input
              type="number"
              min={1}
              value={seq === "" ? String(nextSeq) : seq}
              onChange={(e) => setSeq(e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>
      )}
      <FileDrop
        files={files}
        onChange={setFiles}
        maxCount={MAX_TENDER_FILES - docs.length}
        label="choose files"
      />
      <InlineError error={upload.error} />
      <Button
        variant="primary"
        disabled={files.length === 0 || (kind === "ADDENDUM" && !(seqValue >= 1))}
        busy={upload.isPending}
        onClick={() => upload.mutate()}
      >
        Upload {files.length > 0 ? `${files.length} file(s)` : ""}
      </Button>
      {docs.length > 0 && (
        <div className="space-y-1">
          <h3 className="text-sm font-medium text-slate-800">Uploaded</h3>
          <DocList docs={docs} onDelete={(d) => del.mutate(d)} />
          <InlineError error={del.error} />
        </div>
      )}
    </div>
  );
}

function CompanyDocsPicker({
  selected,
  setSelected,
  useKb,
  setUseKb,
}: {
  selected: Set<string>;
  setSelected: (s: Set<string>) => void;
  useKb: boolean;
  setUseKb: (v: boolean) => void;
}) {
  const qc = useQueryClient();
  const kb = useQuery({ queryKey: qk.kb, queryFn: api.listKnowledgeBase });
  const [files, setFiles] = useState<File[]>([]);
  const [kind, setKind] = useState<CompanyDocumentKind>("COMPANY_PROFILE");

  const upload = useMutation({
    mutationFn: () => api.uploadKnowledgeBase(files, kind),
    onSuccess: (r) => {
      setFiles([]);
      const next = new Set(selected);
      r.documents.forEach((d) => next.add(d.id));
      setSelected(next);
      void qc.invalidateQueries({ queryKey: qk.kb });
    },
  });

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-3">
        <label className="flex items-start gap-2 text-sm text-slate-800">
          <input
            type="checkbox"
            checked={useKb}
            onChange={(e) => setUseKb(e.target.checked)}
            className="mt-0.5 accent-teal-700"
          />
          <span>
            <span className="font-medium">Use the whole knowledge base</span>
            <span className="block text-xs text-slate-600">
              Every company document your organisation has uploaded. Already-processed documents are not re-read.
            </span>
          </span>
        </label>
        <fieldset disabled={useKb} className="space-y-2 disabled:opacity-60">
          <legend className="text-sm font-medium text-slate-800">Or pick documents for this tender</legend>
          {kb.isPending ? (
            <Loading label="Loading knowledge base…" />
          ) : kb.isError ? (
            <ErrorState error={kb.error} title="Could not load the knowledge base" onRetry={() => kb.refetch()} />
          ) : kb.data.items.length === 0 ? (
            <EmptyState title="Knowledge base is empty">Upload your company documents on the right.</EmptyState>
          ) : (
            <ul className="max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-md border border-slate-200 text-sm">
              {kb.data.items.map((d) => (
                <li key={d.id}>
                  <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-slate-50">
                    <input
                      type="checkbox"
                      checked={useKb || selected.has(d.id)}
                      onChange={() => toggle(d.id)}
                      className="accent-teal-700"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-slate-800">{d.filename}</span>
                      <span className="text-xs text-slate-500">{humanize(d.kind)}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </fieldset>
      </div>
      <div className="space-y-3">
        <h3 className="text-sm font-medium text-slate-800">Upload company documents</h3>
        <Field label="Document kind" hint="Certificates, completion letters and audited statements count as documented proof.">
          <select value={kind} onChange={(e) => setKind(e.target.value as CompanyDocumentKind)} className={inputClass}>
            {COMPANY_KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </Field>
        <FileDrop files={files} onChange={setFiles} label="choose files" />
        <InlineError error={upload.error} />
        <Button disabled={files.length === 0} busy={upload.isPending} onClick={() => upload.mutate()}>
          Add to knowledge base
        </Button>
      </div>
    </div>
  );
}

function StartRunButton({
  tenderId,
  disabled,
  companyIds,
  useKb,
}: {
  tenderId: string;
  disabled: boolean;
  companyIds: string[];
  useKb: boolean;
}) {
  const router = useRouter();
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: () =>
      api.startRun(tenderId, {
        use_knowledge_base: useKb,
        ...(useKb ? {} : { company_document_ids: companyIds }),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.tender(tenderId) });
      void qc.invalidateQueries({ queryKey: ["tenders"] });
      router.push(`/tenders/${tenderId}/run`);
    },
  });
  return (
    <div className="space-y-2">
      <Button variant="primary" disabled={disabled} busy={start.isPending} onClick={() => start.mutate()}>
        <Play className="size-4" aria-hidden /> Start analysis
      </Button>
      <InlineError error={start.error} />
    </div>
  );
}

function NewTender() {
  const router = useRouter();
  const params = useSearchParams();
  const tenderId = params.get("tender");
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [useKb, setUseKb] = useState(true);

  const tender = useQuery({
    queryKey: qk.tender(tenderId ?? ""),
    queryFn: () => api.getTender(tenderId!),
    enabled: !!tenderId,
  });

  const create = useMutation({
    mutationFn: () => api.createTender(title.trim() || undefined),
    onSuccess: ({ tender }) => {
      void qc.invalidateQueries({ queryKey: ["tenders"] });
      void qc.invalidateQueries({ queryKey: qk.stats });
      router.replace(`/tenders/new?tender=${tender.id}`);
    },
  });

  const docs = tender.data?.documents ?? [];
  const hasTenderDoc = docs.some((d) => d.kind === "TENDER");
  const hasCompany = useKb || selected.size > 0;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">New tender</h1>
        <p className="text-sm text-slate-600">
          Upload the tender and any addenda, choose your company documents, then start the analysis.
        </p>
      </div>

      <Card title={<StepHeading n={1} title="Tender details" done={!!tenderId} />}>
        {tenderId ? (
          tender.isPending ? (
            <Loading />
          ) : tender.isError ? (
            <ErrorState error={tender.error} title="Could not load this tender" onRetry={() => tender.refetch()} />
          ) : (
            <p className="text-sm text-slate-700">
              <span className="font-medium text-slate-900">{tender.data.tender.title || "Untitled tender"}</span>
              <span className="text-slate-500"> — the title and reference are read from the tender document during analysis.</span>
            </p>
          )
        ) : (
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <div className="min-w-64 flex-1">
              <Field label="Working title (optional)" hint="Leave blank to use the title found in the tender document.">
                <input value={title} onChange={(e) => setTitle(e.target.value)} className={inputClass} maxLength={300} />
              </Field>
            </div>
            <Button type="submit" variant="primary" busy={create.isPending} className="mb-5">
              Create tender
            </Button>
            <div className="w-full">
              <InlineError error={create.error} />
            </div>
          </form>
        )}
      </Card>

      <Card title={<StepHeading n={2} title="Tender documents" done={hasTenderDoc} />}>
        {tenderId && tender.data ? (
          <TenderUploadZone tenderId={tenderId} docs={docs} />
        ) : (
          <p className="text-sm text-slate-500">Create the tender first.</p>
        )}
      </Card>

      <Card title={<StepHeading n={3} title="Company documents" done={!!tenderId && hasCompany} />}>
        <CompanyDocsPicker selected={selected} setSelected={setSelected} useKb={useKb} setUseKb={setUseKb} />
      </Card>

      <Card title={<StepHeading n={4} title="Start analysis" />}>
        <div className="space-y-3 text-sm text-slate-700">
          {!hasTenderDoc && <p>Upload at least one tender document to start.</p>}
          {hasTenderDoc && !hasCompany && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-amber-900">
              No company documents selected. Every requirement will come out as Unverified.
            </p>
          )}
          <p className="text-slate-600">
            The run reads the documents, checks every requirement against your evidence, recommends bid or
            no-bid, and drafts the technical proposal. Nothing is submitted anywhere: you review and approve
            at the end.
          </p>
          {tenderId && (
            <StartRunButton
              tenderId={tenderId}
              disabled={!hasTenderDoc}
              companyIds={[...selected]}
              useKb={useKb}
            />
          )}
        </div>
      </Card>
    </div>
  );
}

export default function NewTenderPage() {
  return (
    <Suspense fallback={<Loading />}>
      <NewTender />
    </Suspense>
  );
}
