"use client";
// Status chips. Colour is never the only cue: every chip carries a text label (and most an icon).

import { CheckCircle2, CircleDashed, CircleHelp, CircleMinus, XCircle } from "lucide-react";
import type {
  ComplianceStatus,
  Confidence,
  FindingSeverity,
  Recommendation,
  RunStatus,
  Severity,
  TenderStatus,
  VerificationStatus,
} from "@/lib/types";
import { Badge, type Tone } from "./ui";

const compliance: Record<ComplianceStatus, { tone: Tone; label: string; Icon: typeof CheckCircle2 }> = {
  COMPLIANT: { tone: "green", label: "Compliant", Icon: CheckCircle2 },
  PARTIAL: { tone: "amber", label: "Partial", Icon: CircleMinus },
  NON_COMPLIANT: { tone: "red", label: "Non-compliant", Icon: XCircle },
  UNVERIFIED: { tone: "grey", label: "Unverified", Icon: CircleHelp },
};

export function ComplianceChip({ status }: { status: ComplianceStatus }) {
  const c = compliance[status] ?? compliance.UNVERIFIED;
  return (
    <Badge tone={c.tone}>
      <c.Icon className="size-3.5" aria-hidden />
      {c.label}
    </Badge>
  );
}

export const complianceLabel = (s: ComplianceStatus) => compliance[s]?.label ?? s;

const tender: Record<TenderStatus, { tone: Tone; label: string }> = {
  DRAFT: { tone: "grey", label: "Draft" },
  PROCESSING: { tone: "blue", label: "Processing" },
  AWAITING_REVIEW: { tone: "amber", label: "Awaiting review" },
  CHANGES_REQUESTED: { tone: "amber", label: "Changes requested" },
  APPROVED: { tone: "green", label: "Approved" },
  FAILED: { tone: "red", label: "Failed" },
};

export function TenderStatusChip({ status }: { status: TenderStatus }) {
  const t = tender[status] ?? { tone: "grey" as Tone, label: status };
  return <Badge tone={t.tone}>{t.label}</Badge>;
}

const run: Record<RunStatus, { tone: Tone; label: string }> = {
  PENDING: { tone: "grey", label: "Queued" },
  RUNNING: { tone: "blue", label: "Running" },
  WAITING_REVIEW: { tone: "amber", label: "Waiting for review" },
  COMPLETED: { tone: "green", label: "Completed" },
  FAILED: { tone: "red", label: "Failed" },
  CANCELLED: { tone: "grey", label: "Cancelled" },
};

export function RunStatusChip({ status }: { status: RunStatus }) {
  const r = run[status] ?? { tone: "grey" as Tone, label: status };
  return (
    <Badge tone={r.tone}>
      {status === "RUNNING" && <CircleDashed className="size-3.5 animate-spin" aria-hidden />}
      {r.label}
    </Badge>
  );
}

const rec: Record<Recommendation, { tone: Tone; label: string }> = {
  BID: { tone: "green", label: "Bid" },
  BID_WITH_CONDITIONS: { tone: "amber", label: "Bid with conditions" },
  NO_BID: { tone: "red", label: "No bid" },
};

export function RecommendationBadge({ value }: { value: Recommendation }) {
  return <Badge tone={rec[value]?.tone ?? "grey"}>{rec[value]?.label ?? value}</Badge>;
}

const severityTone: Record<Severity | FindingSeverity, Tone> = {
  BLOCKER: "red",
  MAJOR: "amber",
  HIGH: "amber",
  MEDIUM: "blue",
  MINOR: "grey",
  LOW: "grey",
};

export function SeverityBadge({ value }: { value: Severity | FindingSeverity }) {
  return <Badge tone={severityTone[value] ?? "grey"}>{value.charAt(0) + value.slice(1).toLowerCase()}</Badge>;
}

const confTone: Record<Confidence, Tone> = { HIGH: "green", MEDIUM: "blue", LOW: "amber" };

export function ConfidenceBadge({ value }: { value: Confidence }) {
  return (
    <Badge tone={confTone[value] ?? "grey"} title="Extraction confidence">
      {value.charAt(0) + value.slice(1).toLowerCase()}
    </Badge>
  );
}

const verTone: Record<VerificationStatus, { tone: Tone; label: string }> = {
  DOCUMENTED: { tone: "green", label: "Documented" },
  SELF_DECLARED: { tone: "amber", label: "Self-declared" },
  EXPIRED: { tone: "red", label: "Expired" },
  UNVERIFIED: { tone: "grey", label: "Unverified" },
};

export function VerificationBadge({ value }: { value: VerificationStatus }) {
  const v = verTone[value] ?? { tone: "grey" as Tone, label: value };
  return <Badge tone={v.tone}>{v.label}</Badge>;
}

/** Plain-language meaning of each compliance rule (PRD §8.1). */
export const RULE_EXPLANATIONS: Record<string, string> = {
  R1: "Invalid evidence codes were dropped before the decision.",
  R2: "No evidence was cited, so it cannot be marked compliant.",
  R3: "Decided by calculation from the numeric criterion (e.g. turnover, project count).",
  R4: "All cited evidence has expired.",
  R5: "Only self-declared or unverified evidence, so capped at Partial until proof is provided.",
  R6: "Documented, valid evidence with a high-confidence match.",
  R7: "The model's assessment, capped at Partial without strong documented proof.",
};
