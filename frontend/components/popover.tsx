"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { cx, focusRing } from "./ui";

/** Click-to-open popover. Esc or a click outside closes it; focus returns to the trigger. */
export function Popover({
  trigger,
  label,
  children,
  triggerClassName,
}: {
  trigger: ReactNode;
  label: string;
  children: ReactNode;
  triggerClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const wrap = useRef<HTMLSpanElement>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    panel.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        btn.current?.focus();
      }
    };
    // Fixed positioning escapes overflow-clipped table containers; close if the page moves.
    const onMove = (e: Event) => {
      if (!panel.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [open]);

  return (
    <span ref={wrap} className="inline-block">
      <button
        ref={btn}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        aria-label={label}
        onClick={() => {
          const r = btn.current?.getBoundingClientRect();
          if (r) {
            const width = 336;
            const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
            const below = window.innerHeight - r.bottom > 260;
            setPos({ top: below ? r.bottom + 4 : Math.max(8, r.top - 264), left });
          }
          setOpen((o) => !o);
        }}
        className={cx(focusRing, triggerClassName)}
      >
        {trigger}
      </button>
      {open && (
        <div
          ref={panel}
          id={id}
          role="dialog"
          aria-label={label}
          tabIndex={-1}
          style={{ top: pos.top, left: pos.left }}
          className="fixed z-40 max-h-64 w-[21rem] overflow-y-auto rounded-md border border-slate-200 bg-white p-3 text-left text-sm shadow-lg outline-none"
        >
          {children}
        </div>
      )}
    </span>
  );
}
