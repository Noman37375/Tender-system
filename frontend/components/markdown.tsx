"use client";
// Minimal, safe Markdown renderer (no HTML injection): headings, paragraphs, lists, tables,
// bold/italic/code, and `[CLIENT INPUT REQUIRED: …]` rendered as a highlighted inline badge.

import { Fragment, type ReactNode } from "react";

const PLACEHOLDER_RE = /\[CLIENT INPUT REQUIRED:\s*([^\]]*)\]/g;

export function PlaceholderBadge({ text }: { text: string }) {
  return (
    <mark
      className="mx-0.5 inline rounded border border-amber-400 bg-amber-100 px-1.5 py-0.5 text-[0.85em] font-medium text-amber-950"
      title="Client input required"
    >
      <span className="sr-only">Client input required: </span>
      <span aria-hidden>Input needed: </span>
      {text}
    </mark>
  );
}

function emphasis(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const k = `${keyBase}-${i++}`;
    if (tok.startsWith("**") || tok.startsWith("__")) out.push(<strong key={k}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`"))
      out.push(
        <code key={k} className="rounded bg-slate-100 px-1 text-[0.9em]">
          {tok.slice(1, -1)}
        </code>,
      );
    else out.push(<em key={k}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Inline({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(PLACEHOLDER_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) out.push(<Fragment key={`t${i}`}>{emphasis(text.slice(last, idx), `e${i}`)}</Fragment>);
    out.push(<PlaceholderBadge key={`p${i}`} text={m[1].trim()} />);
    last = idx + m[0].length;
    i++;
  }
  if (last < text.length) out.push(<Fragment key="tail">{emphasis(text.slice(last), "tail")}</Fragment>);
  return <>{out}</>;
}

const splitRow = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());

const isTableSep = (line: string | undefined) => !!line && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line);

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const cls = [
        "text-xl font-semibold mt-6",
        "text-lg font-semibold mt-5",
        "text-base font-semibold mt-4",
        "text-sm font-semibold mt-3",
        "text-sm font-semibold mt-3",
        "text-sm font-semibold mt-3",
      ][level - 1];
      const Tag = `h${Math.min(level + 1, 6)}` as "h2";
      blocks.push(
        <Tag key={key++} className={`${cls} text-slate-900 first:mt-0`}>
          <Inline text={h[2]} />
        </Tag>,
      );
      i++;
      continue;
    }
    if (line.trim().startsWith("|") && isTableSep(lines[i + 1])) {
      const header = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      blocks.push(
        <div key={key++} className="my-3 overflow-x-auto">
          <table className="min-w-full border-collapse text-sm">
            <thead>
              <tr>
                {header.map((c, j) => (
                  <th key={j} className="border border-slate-300 bg-slate-50 px-2 py-1 text-left font-semibold">
                    <Inline text={c} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, ri) => (
                <tr key={ri}>
                  {r.map((c, j) => (
                    <td key={j} className="border border-slate-200 px-2 py-1 align-top">
                      <Inline text={c} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const ul = /^\s*[-*+]\s+/;
    const ol = /^\s*\d+[.)]\s+/;
    if (ul.test(line) || ol.test(line)) {
      const ordered = ol.test(line);
      const re = ordered ? ol : ul;
      const items: string[] = [];
      while (i < lines.length && re.test(lines[i])) items.push(lines[i++].replace(re, ""));
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(
        <ListTag key={key++} className={`my-2 space-y-1 pl-6 ${ordered ? "list-decimal" : "list-disc"}`}>
          {items.map((it, j) => (
            <li key={j}>
              <Inline text={it} />
            </li>
          ))}
        </ListTag>,
      );
      continue;
    }
    if (line.startsWith(">")) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      blocks.push(
        <blockquote key={key++} className="my-3 border-l-4 border-slate-300 pl-3 text-slate-700">
          <Inline text={quote.join(" ")} />
        </blockquote>,
      );
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,6})\s/.test(lines[i]) &&
      !ul.test(lines[i]) &&
      !ol.test(lines[i]) &&
      !lines[i].startsWith(">") &&
      !(lines[i].trim().startsWith("|") && isTableSep(lines[i + 1]))
    )
      para.push(lines[i++]);
    blocks.push(
      <p key={key++} className="my-2 leading-relaxed">
        <Inline text={para.join(" ")} />
      </p>,
    );
  }

  return <div className="text-sm text-slate-800">{blocks}</div>;
}
