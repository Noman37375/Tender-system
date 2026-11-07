"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo } from "react";
import { SourcePreviewProvider } from "@/components/source-preview";
import { RunStatusChip, TenderStatusChip } from "@/components/status";
import { ErrorState, Loading, cx, focusRing, formatDate } from "@/components/ui";
import { api } from "@/lib/api";
import { qk, useTender, useTenderId } from "@/lib/hooks";

const TABS = [
  { slug: "run", label: "Run" },
  { slug: "analysis", label: "Analysis" },
  { slug: "compliance", label: "Compliance" },
  { slug: "proposal", label: "Proposal" },
  { slug: "review", label: "Review" },
];

export default function TenderLayout({ children }: { children: React.ReactNode }) {
  const tenderId = useTenderId();
  const path = usePathname();
  const tender = useTender(tenderId);
  // Company evidence cites knowledge-base documents, so source chips need their names too.
  const kb = useQuery({ queryKey: qk.kb, queryFn: api.listKnowledgeBase, retry: false });

  const documents = useMemo(
    () => [...(tender.data?.documents ?? []), ...(kb.data?.items ?? [])],
    [tender.data, kb.data],
  );

  if (tender.isPending) return <Loading label="Loading tender…" />;
  if (tender.isError)
    return <ErrorState error={tender.error} title="Could not load this tender" onRetry={() => tender.refetch()} notReadyText="This tender does not exist or you do not have access to it." />;

  const { tender: t, latest_run } = tender.data;

  return (
    <SourcePreviewProvider documents={documents}>
      <div className="space-y-5">
        <div>
          <Link href="/dashboard" className={cx("inline-flex items-center gap-1 rounded text-sm text-slate-600 hover:text-slate-900", focusRing)}>
            <ChevronLeft className="size-4" aria-hidden /> Dashboard
          </Link>
          <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold text-slate-900">{t.title || "Untitled tender"}</h1>
              <p className="text-sm text-slate-600">
                {[t.reference_no, t.procuring_entity].filter(Boolean).join(" · ") || "Reference not yet extracted"}
                {t.submission_deadline && <> · Deadline {formatDate(t.submission_deadline, true)}</>}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <TenderStatusChip status={t.status} />
              {latest_run && <RunStatusChip status={latest_run.status} />}
            </div>
          </div>
        </div>
        <nav aria-label="Tender sections" className="border-b border-slate-200">
          <ul className="-mb-px flex gap-1 overflow-x-auto">
            {TABS.map((tab) => {
              const href = `/tenders/${tenderId}/${tab.slug}`;
              const active = path === href;
              return (
                <li key={tab.slug}>
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={cx(
                      "block whitespace-nowrap border-b-2 px-3 py-2 text-sm",
                      active
                        ? "border-teal-700 font-medium text-teal-800"
                        : "border-transparent text-slate-600 hover:border-slate-300 hover:text-slate-900",
                      focusRing,
                    )}
                  >
                    {tab.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        {children}
      </div>
    </SourcePreviewProvider>
  );
}
