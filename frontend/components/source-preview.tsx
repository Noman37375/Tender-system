"use client";
// Source chip "Doc · p.12" and the page preview drawer with the quote highlighted (PRD §11.2).

import { useQuery } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api";
import type { SourceRef } from "@/lib/types";
import { Dialog, ErrorState, Loading, cx, focusRing } from "./ui";

interface Ctx {
  open: (src: SourceRef) => void;
  docName: (documentId: string) => string;
}

const SourceCtx = createContext<Ctx | null>(null);

export function SourcePreviewProvider({
  documents,
  children,
}: {
  documents: { id: string; filename: string }[];
  children: ReactNode;
}) {
  const [src, setSrc] = useState<SourceRef | null>(null);
  const names = useMemo(() => new Map(documents.map((d) => [d.id, d.filename])), [documents]);
  const docName = useCallback((id: string) => names.get(id) ?? "Document", [names]);
  const value = useMemo(() => ({ open: setSrc, docName }), [docName]);

  return (
    <SourceCtx.Provider value={value}>
      {children}
      <Dialog
        open={src !== null}
        onClose={() => setSrc(null)}
        variant="drawer"
        title={src ? `${docName(src.document_id)} · page ${src.page}` : "Source"}
        description="Source page as extracted. The cited quote is highlighted."
      >
        {src && <PagePreview src={src} />}
      </Dialog>
    </SourceCtx.Provider>
  );
}

export function useSourcePreview(): Ctx {
  return (
    useContext(SourceCtx) ?? {
      open: () => undefined,
      docName: () => "Document",
    }
  );
}

function shortName(name: string) {
  const base = name.replace(/\.(pdf|docx)$/i, "");
  return base.length > 22 ? `${base.slice(0, 20)}…` : base;
}

export function SourceChip({ source, className }: { source: SourceRef | null | undefined; className?: string }) {
  const { open, docName } = useSourcePreview();
  if (!source) return <span className="text-xs text-slate-500">No source</span>;
  const name = docName(source.document_id);
  return (
    <button
      type="button"
      onClick={() => open(source)}
      title={`Open ${name}, page ${source.page}`}
      aria-label={`Open source: ${name}, page ${source.page}`}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-xs text-slate-700 hover:border-teal-700 hover:text-teal-800",
        focusRing,
        className,
      )}
    >
      <FileText className="size-3" aria-hidden />
      {shortName(name)} · p.{source.page}
    </button>
  );
}

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Find the quote in the page text, tolerating case and whitespace differences. */
export function findQuote(text: string, quote: string): [number, number] | null {
  const q = quote.trim();
  if (!q) return null;
  const exact = text.indexOf(q);
  if (exact >= 0) return [exact, exact + q.length];
  const words = q.split(/\s+/).filter(Boolean).map(escapeRe);
  if (!words.length) return null;
  const m = new RegExp(words.join("\\s+"), "i").exec(text);
  return m ? [m.index, m.index + m[0].length] : null;
}

function PagePreview({ src }: { src: SourceRef }) {
  const q = useQuery({
    queryKey: ["page", src.document_id, src.page],
    queryFn: () => api.getPage(src.document_id, src.page),
    staleTime: Infinity,
  });
  const markRef = useRef<HTMLElement>(null);
  const range = q.data ? findQuote(q.data.text, src.quote) : null;

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center" });
  }, [q.data]);

  return (
    <div className="space-y-4">
      {src.quote && (
        <figure className="rounded-md border-l-4 border-amber-400 bg-amber-50 px-3 py-2 text-sm text-slate-800">
          <figcaption className="mb-1 text-xs font-medium uppercase tracking-wide text-amber-900">
            Cited quote
          </figcaption>
          <blockquote>&ldquo;{src.quote}&rdquo;</blockquote>
        </figure>
      )}
      {q.isPending && <Loading label="Loading page…" />}
      {q.isError && (
        <ErrorState error={q.error} onRetry={() => q.refetch()} notReadyText="This page has not been extracted." />
      )}
      {q.data && (
        <>
          {src.quote && !range && (
            <p className="text-sm text-amber-900">
              The exact quote was not found on this page (it may span pages or differ slightly after extraction).
            </p>
          )}
          <pre className="whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-50 p-4 font-sans text-sm leading-relaxed text-slate-800">
            {range ? (
              <>
                {q.data.text.slice(0, range[0])}
                <mark ref={markRef} className="rounded bg-amber-200 px-0.5 text-slate-900">
                  {q.data.text.slice(range[0], range[1])}
                </mark>
                {q.data.text.slice(range[1])}
              </>
            ) : (
              q.data.text || "(No text on this page)"
            )}
          </pre>
          {q.data.tables?.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-800">Tables on this page</h3>
              {q.data.tables.map((t, i) => (
                <div key={i} className="overflow-x-auto">
                  <table className="min-w-full border-collapse text-xs">
                    <tbody>
                      {(t.rows ?? []).map((row, r) => (
                        <tr key={r}>
                          {row.map((cell, c) => (
                            <td key={c} className="border border-slate-200 px-2 py-1 align-top">
                              {cell ?? ""}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
