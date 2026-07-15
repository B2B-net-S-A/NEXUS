/**
 * Turn a bulk-add response into human-readable per-reason counts for the result
 * banner. The endpoint returns exact per-candidate reasons (incl. client
 * conflicts) and warnings for added-but-flagged candidates (SEARCH-P0-04); the
 * UI previously showed only a hardcoded "już w jobie / blacklist" string.
 */

import type {
  BulkProposalsResponse,
  BulkSkipReason,
  BulkWarningReason,
} from "@/lib/candidate-search-api";

const SKIP_LABELS: Record<BulkSkipReason, string> = {
  already_in_job: "już w rekrutacji",
  blacklisted: "czarna lista",
  candidate_not_found: "nie znaleziono",
  client_blacklist: "konflikt: czarna lista klienta",
  client_nda: "konflikt: NDA z klientem",
  client_competitor: "konflikt: klient konkurencyjny",
};

const WARNING_LABELS: Record<BulkWarningReason, string> = {
  current_employment: "obecne zatrudnienie u klienta",
  excluded_by_candidate: "kandydat wykluczył klienta",
};

export interface ReasonCount {
  label: string;
  count: number;
}

export interface BulkResultSummary {
  added: number;
  skipped: ReasonCount[];
  warnings: ReasonCount[];
}

function tally<T extends string>(
  rows: ReadonlyArray<{ reason: T }>,
  labels: Record<T, string>,
): ReasonCount[] {
  const counts = new Map<string, number>();
  for (const row of rows) {
    const label = labels[row.reason] ?? row.reason;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return Array.from(counts, ([label, count]) => ({ label, count }));
}

export function summarizeBulkResult(
  resp: BulkProposalsResponse,
): BulkResultSummary {
  return {
    added: resp.total_added,
    skipped: tally(resp.skipped, SKIP_LABELS),
    warnings: tally(resp.warnings ?? [], WARNING_LABELS),
  };
}

/** Render "2× konflikt: NDA z klientem, 1× już w rekrutacji". */
export function formatReasonCounts(items: ReasonCount[]): string {
  return items.map((i) => `${i.count}× ${i.label}`).join(", ");
}
