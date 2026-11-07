"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { TenderStatusChip } from "@/components/status";
import { Button, Card, EmptyState, ErrorState, LinkButton, Loading, cx, focusRing, formatDate } from "@/components/ui";
import { api } from "@/lib/api";
import { qk } from "@/lib/hooks";

const PAGE_SIZE = 20;

function StatCards() {
  const stats = useQuery({ queryKey: qk.stats, queryFn: api.dashboardStats });
  const cards = [
    { key: "tenders", label: "Tenders", hint: "All tenders in your organisation" },
    { key: "awaiting_review", label: "Awaiting review", hint: "Drafts waiting for a human decision" },
    { key: "approved", label: "Approved", hint: "Approved and ready to export" },
  ] as const;

  if (stats.isError)
    return <ErrorState error={stats.error} title="Could not load statistics" onRetry={() => stats.refetch()} />;

  return (
    <dl className="grid gap-4 sm:grid-cols-3">
      {cards.map((c) => (
        <div key={c.key} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <dt className="text-sm font-medium text-slate-600">{c.label}</dt>
          <dd className="mt-1 text-3xl font-semibold tabular-nums text-slate-900">
            {stats.isPending ? <span className="text-slate-300">—</span> : stats.data[c.key]}
          </dd>
          <dd className="mt-1 text-xs text-slate-500">{c.hint}</dd>
        </div>
      ))}
    </dl>
  );
}

function RecentTenders() {
  const [page, setPage] = useState(1);
  const list = useQuery({
    queryKey: qk.tenders(page),
    queryFn: () => api.listTenders({ page, page_size: PAGE_SIZE }),
    placeholderData: (prev) => prev,
  });

  return (
    <Card title="Recent tenders" bodyClassName="p-0">
      {list.isPending ? (
        <Loading label="Loading tenders…" />
      ) : list.isError ? (
        <div className="p-4">
          <ErrorState error={list.error} title="Could not load tenders" onRetry={() => list.refetch()} />
        </div>
      ) : list.data.items.length === 0 ? (
        <div className="p-4">
          <EmptyState
            title="No tenders yet"
            action={
              <LinkButton href="/tenders/new" variant="primary">
                <Plus className="size-4" aria-hidden /> New tender
              </LinkButton>
            }
          >
            Upload a tender document and your company documents to get a compliance check, a bid/no-bid
            recommendation and a draft technical proposal.
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <caption className="sr-only">Recent tenders</caption>
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Tender</th>
                  <th scope="col" className="px-4 py-2 font-medium">Procuring entity</th>
                  <th scope="col" className="px-4 py-2 font-medium">Deadline</th>
                  <th scope="col" className="px-4 py-2 font-medium">Status</th>
                  <th scope="col" className="px-4 py-2 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {list.data.items.map((t) => (
                  <tr key={t.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5">
                      <Link
                        href={t.status === "DRAFT" ? `/tenders/new?tender=${t.id}` : `/tenders/${t.id}/run`}
                        className={cx("rounded font-medium text-teal-800 hover:underline", focusRing)}
                      >
                        {t.title || "Untitled tender"}
                      </Link>
                      {t.reference_no && <p className="text-xs text-slate-500">{t.reference_no}</p>}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">{t.procuring_entity ?? "—"}</td>
                    <td className="px-4 py-2.5 text-slate-700">{formatDate(t.submission_deadline)}</td>
                    <td className="px-4 py-2.5">
                      <TenderStatusChip status={t.status} />
                    </td>
                    <td className="px-4 py-2.5 text-slate-600">{formatDate(t.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {list.data.total > PAGE_SIZE && (
            <nav aria-label="Pagination" className="flex items-center justify-between border-t border-slate-200 px-4 py-2 text-sm text-slate-600">
              <span>
                Page {page} of {Math.ceil(list.data.total / PAGE_SIZE)} · {list.data.total} tenders
              </span>
              <div className="flex gap-2">
                <Button size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  <ChevronLeft className="size-4" aria-hidden /> Previous
                </Button>
                <Button size="sm" disabled={page * PAGE_SIZE >= list.data.total} onClick={() => setPage((p) => p + 1)}>
                  Next <ChevronRight className="size-4" aria-hidden />
                </Button>
              </div>
            </nav>
          )}
        </>
      )}
    </Card>
  );
}

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Dashboard</h1>
          <p className="text-sm text-slate-600">Your bid office at a glance.</p>
        </div>
        <LinkButton href="/tenders/new" variant="primary">
          <Plus className="size-4" aria-hidden /> New tender
        </LinkButton>
      </div>
      <StatCards />
      <RecentTenders />
    </div>
  );
}
