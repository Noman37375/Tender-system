"use client";

import { EmptyState, LinkButton } from "./ui";

/** Shown on tender tabs when the tender has never been run. */
export function NoRun({ tenderId }: { tenderId: string }) {
  return (
    <EmptyState
      title="This tender has not been analysed yet"
      action={
        <LinkButton href={`/tenders/new?tender=${tenderId}`} variant="primary">
          Upload documents and start
        </LinkButton>
      }
    >
      Start a run to extract requirements, check compliance and draft the proposal.
    </EmptyState>
  );
}
