"use client";
// Signed-in shell: auth guard + app header for /dashboard and /tenders/*.

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppHeader } from "@/components/app-header";
import { ErrorState, Loading } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/hooks";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const me = useMe();
  const unauthorised = me.error instanceof ApiError && me.error.status === 401;

  useEffect(() => {
    if (unauthorised) {
      api.logout();
      router.replace("/login");
    }
  }, [unauthorised, router]);

  return (
    <div className="min-h-screen bg-slate-50">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:shadow"
      >
        Skip to content
      </a>
      <AppHeader me={me.data} />
      <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        {me.isPending || unauthorised ? (
          <Loading label="Checking your session…" />
        ) : me.isError ? (
          <ErrorState error={me.error} title="Could not load your account" onRetry={() => me.refetch()} />
        ) : (
          children
        )}
      </main>
    </div>
  );
}
