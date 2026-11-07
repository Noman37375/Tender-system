"use client";
// Small, dependency-free UI kit: calm "bid office" look, slate text, one teal accent.

import { AlertTriangle, Inbox, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useId, useRef, type ComponentProps, type ReactNode } from "react";
import { ApiError, errorMessage } from "@/lib/api";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- buttons

type Variant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-teal-700 text-white hover:bg-teal-800 border border-teal-700",
  secondary: "bg-white text-slate-800 border border-slate-300 hover:bg-slate-50",
  danger: "bg-red-700 text-white hover:bg-red-800 border border-red-700",
  ghost: "text-slate-700 hover:bg-slate-100 border border-transparent",
};

export const focusRing =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700";

export function buttonClass(variant: Variant = "secondary", size: "sm" | "md" = "md") {
  return cx(
    "inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-50",
    size === "sm" ? "px-2.5 py-1 text-sm" : "px-3.5 py-2 text-sm",
    variants[variant],
    focusRing,
  );
}

export function Button({
  variant = "secondary",
  size = "md",
  busy,
  className,
  children,
  disabled,
  type = "button",
  ...rest
}: ComponentProps<"button"> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean }) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(buttonClass(variant, size), className)}
      {...rest}
    >
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({
  variant = "secondary",
  size = "md",
  className,
  ...rest
}: ComponentProps<typeof Link> & { variant?: Variant; size?: "sm" | "md" }) {
  return <Link className={cx(buttonClass(variant, size), className)} {...rest} />;
}

// ---------------------------------------------------------------- layout

export function Card({
  title,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
          {title && <h2 className="text-base font-semibold text-slate-900">{title}</h2>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------- states

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-sm text-slate-600">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white px-6 py-10 text-center">
      <Inbox className="size-6 text-slate-400" aria-hidden />
      <p className="font-medium text-slate-800">{title}</p>
      {children && <div className="max-w-prose text-sm text-slate-600">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** True when the backend says the result does not exist yet (run has not reached that step). */
export function isNotReady(err: unknown) {
  return err instanceof ApiError && (err.status === 404 || err.status === 409);
}

export function ErrorState({
  error,
  onRetry,
  title = "Something went wrong",
  notReadyText = "This result is not available yet. It appears once the run reaches this step.",
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  notReadyText?: string;
}) {
  if (isNotReady(error)) return <EmptyState title="Not ready yet">{notReadyText}</EmptyState>;
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900"
    >
      <p className="flex items-center gap-2 font-medium">
        <AlertTriangle className="size-4" aria-hidden />
        {title}
      </p>
      <p>{errorMessage(error)}</p>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
      {errorMessage(error)}
    </p>
  );
}

// ---------------------------------------------------------------- badges & chips

export type Tone = "green" | "amber" | "red" | "grey" | "blue" | "teal";

const tones: Record<Tone, string> = {
  green: "bg-green-50 text-green-800 ring-green-600/30",
  amber: "bg-amber-50 text-amber-900 ring-amber-600/40",
  red: "bg-red-50 text-red-800 ring-red-600/30",
  grey: "bg-slate-100 text-slate-700 ring-slate-500/30",
  blue: "bg-sky-50 text-sky-800 ring-sky-600/30",
  teal: "bg-teal-50 text-teal-800 ring-teal-600/30",
};

export function Badge({
  tone = "grey",
  children,
  className,
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- dialogs (native <dialog>)

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  variant = "modal",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  variant?: "modal" | "drawer";
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby={titleId}
      aria-describedby={description ? descId : undefined}
      onClick={(e) => {
        if (e.target === ref.current) onClose(); // click on backdrop
      }}
      className={cx(
        "bg-white text-slate-900 shadow-xl backdrop:bg-slate-900/40",
        variant === "modal"
          ? "m-auto w-[min(36rem,calc(100vw-2rem))] rounded-lg"
          : "fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-dvh w-[min(44rem,100vw)] max-w-none",
      )}
    >
      {open && (
        <div className={cx("flex flex-col", variant === "drawer" && "h-full")}>
          <header className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4">
            <div>
              <h2 id={titleId} className="text-lg font-semibold">
                {title}
              </h2>
              {description && (
                <p id={descId} className="mt-0.5 text-sm text-slate-600">
                  {description}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              className={cx("rounded p-1 text-slate-500 hover:bg-slate-100", focusRing)}
              aria-label="Close"
            >
              <X className="size-5" aria-hidden />
            </button>
          </header>
          <div className={cx("px-5 py-4", variant === "drawer" && "flex-1 overflow-y-auto")}>
            {children}
          </div>
          {footer && (
            <footer className="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-5 py-3">
              {footer}
            </footer>
          )}
        </div>
      )}
    </dialog>
  );
}

// ---------------------------------------------------------------- form bits

export const inputClass = cx(
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900",
  "placeholder:text-slate-400 focus:border-teal-700 focus:outline-2 focus:outline-teal-700/30",
);

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="block space-y-1 text-sm">
      <span className="font-medium text-slate-800">{label}</span>
      {children}
      {hint && <span className="block text-xs text-slate-600">{hint}</span>}
    </label>
  );
}

// ---------------------------------------------------------------- formatting

export function formatDate(iso: string | null | undefined, withTime = false) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export function formatBytes(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function toNumber(v: number | string | null | undefined) {
  const n = typeof v === "string" ? parseFloat(v) : (v ?? 0);
  return Number.isFinite(n) ? n : 0;
}

export function formatUsd(v: number | string | null | undefined) {
  return `$${toNumber(v).toFixed(toNumber(v) < 1 ? 4 : 2)}`;
}

export function humanize(s: string) {
  const t = s.replace(/_/g, " ").toLowerCase();
  return t.charAt(0).toUpperCase() + t.slice(1);
}
