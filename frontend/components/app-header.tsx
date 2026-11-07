"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileStack, LogOut, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { MeResponse } from "@/lib/types";
import { buttonClass, cx, focusRing } from "./ui";

export function AppHeader({ me }: { me: MeResponse | undefined }) {
  const router = useRouter();
  const qc = useQueryClient();
  const path = usePathname();

  function signOut() {
    api.logout();
    qc.clear();
    router.replace("/login");
  }

  const nav = [
    { href: "/dashboard", label: "Dashboard" },
    { href: "/tenders/new", label: "New tender" },
  ];

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/dashboard" className={cx("flex items-center gap-2 rounded font-semibold text-slate-900", focusRing)}>
          <FileStack className="size-5 text-teal-700" aria-hidden />
          TenderIQ
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1">
          {nav.map((n) => {
            const active = path === n.href;
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "rounded-md px-2.5 py-1.5 text-sm",
                  active ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:text-slate-900",
                  focusRing,
                )}
              >
                {n.href === "/tenders/new" && <Plus className="mr-1 inline size-3.5" aria-hidden />}
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {me && (
            <div className="text-right text-sm leading-tight">
              <p className="font-medium text-slate-900">{me.organisation.name}</p>
              <p className="text-xs text-slate-600">
                {me.user.name} · {me.user.role.replace(/_/g, " ")}
              </p>
            </div>
          )}
          <button type="button" onClick={signOut} className={buttonClass("secondary", "sm")}>
            <LogOut className="size-4" aria-hidden />
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
