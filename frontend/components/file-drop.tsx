"use client";
// Drag-and-drop + file picker for PDF/DOCX. Validates type, size and count client-side
// (PRD §10.2 limits); the server re-validates by magic bytes.

import { Upload, X } from "lucide-react";
import { useId, useRef, useState } from "react";
import { cx, focusRing, formatBytes } from "./ui";

export const MAX_FILE_BYTES = 50 * 1024 * 1024;
const ALLOWED_MIME = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const ALLOWED_EXT = /\.(pdf|docx)$/i;

export function validateFiles(files: File[], maxCount: number): { ok: File[]; errors: string[] } {
  const ok: File[] = [];
  const errors: string[] = [];
  for (const f of files) {
    if (!ALLOWED_MIME.includes(f.type) && !ALLOWED_EXT.test(f.name)) {
      errors.push(`${f.name}: only PDF or DOCX files are accepted.`);
    } else if (f.size > MAX_FILE_BYTES) {
      errors.push(`${f.name}: larger than 50 MB.`);
    } else if (f.size === 0) {
      errors.push(`${f.name}: the file is empty.`);
    } else {
      ok.push(f);
    }
  }
  if (ok.length > maxCount) {
    errors.push(`Only ${maxCount} more file(s) can be added.`);
    ok.length = Math.max(0, maxCount);
  }
  return { ok, errors };
}

export function FileDrop({
  files,
  onChange,
  maxCount = 30,
  label,
  disabled,
}: {
  files: File[];
  onChange: (files: File[]) => void;
  maxCount?: number;
  label: string;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const hintId = useId();

  function add(list: FileList | null) {
    if (!list) return;
    const { ok, errors } = validateFiles(Array.from(list), maxCount - files.length);
    setErrors(errors);
    const names = new Set(files.map((f) => f.name + f.size));
    onChange([...files, ...ok.filter((f) => !names.has(f.name + f.size))]);
  }

  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          if (!disabled) add(e.dataTransfer.files);
        }}
        className={cx(
          "flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors",
          over ? "border-teal-600 bg-teal-50" : "border-slate-300 bg-slate-50",
          disabled && "opacity-60",
        )}
      >
        <Upload className="size-6 text-slate-500" aria-hidden />
        <p className="text-sm text-slate-700">
          Drag files here, or{" "}
          <button
            type="button"
            disabled={disabled}
            onClick={() => inputRef.current?.click()}
            aria-describedby={hintId}
            className={cx("rounded font-medium text-teal-800 underline disabled:no-underline", focusRing)}
          >
            {label}
          </button>
        </p>
        <p id={hintId} className="text-xs text-slate-500">
          PDF or DOCX, up to 50 MB each
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      {errors.length > 0 && (
        <ul role="alert" className="space-y-0.5 text-sm text-red-800">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {files.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 bg-white text-sm" aria-label="Files to upload">
          {files.map((f, i) => (
            <li key={f.name + f.size} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span className="truncate text-slate-800">{f.name}</span>
              <span className="flex items-center gap-2">
                <span className="text-xs text-slate-500">{formatBytes(f.size)}</span>
                <button
                  type="button"
                  onClick={() => onChange(files.filter((_, j) => j !== i))}
                  className={cx("rounded p-0.5 text-slate-500 hover:bg-slate-100", focusRing)}
                  aria-label={`Remove ${f.name}`}
                >
                  <X className="size-4" aria-hidden />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
