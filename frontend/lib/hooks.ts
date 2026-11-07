"use client";
// Shared TanStack Query hooks and query keys.

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api } from "./api";
import { TERMINAL_RUN_STATUSES, type RunStatus } from "./types";

export const qk = {
  me: ["me"] as const,
  stats: ["dashboard-stats"] as const,
  tenders: (page: number) => ["tenders", page] as const,
  tender: (id: string) => ["tender", id] as const,
  kb: ["kb-docs"] as const,
  run: (id: string) => ["run", id] as const,
  analysis: (id: string) => ["analysis", id] as const,
  compliance: (id: string) => ["compliance", id] as const,
  bid: (id: string) => ["bid-decision", id] as const,
  missing: (id: string) => ["missing", id] as const,
  proposal: (id: string) => ["proposal", id] as const,
  forms: (id: string) => ["forms", id] as const,
};

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: api.me, staleTime: 5 * 60_000 });
}

export function useTenderId(): string {
  const p = useParams<{ tenderId: string }>();
  return p.tenderId;
}

export function isActive(status: RunStatus | undefined) {
  return !!status && !TERMINAL_RUN_STATUSES.includes(status);
}

/** GET /tenders/{id}. While a run is active it refreshes every 10 s so tabs pick up the run state. */
export function useTender(tenderId: string) {
  return useQuery({
    queryKey: qk.tender(tenderId),
    queryFn: () => api.getTender(tenderId),
    enabled: !!tenderId,
    refetchInterval: (q) => (isActive(q.state.data?.latest_run?.status) ? 10_000 : false),
  });
}

/** The latest run of the tender in the URL (null when none). */
export function useLatestRun() {
  const tenderId = useTenderId();
  const tender = useTender(tenderId);
  return { tenderId, tender, run: tender.data?.latest_run ?? null };
}
