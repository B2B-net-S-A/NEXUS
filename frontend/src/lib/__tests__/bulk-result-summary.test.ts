import { describe, expect, it } from "vitest";

import type { BulkProposalsResponse } from "@/lib/candidate-search-api";
import {
  formatReasonCounts,
  summarizeBulkResult,
} from "@/lib/bulk-result-summary";

const resp: BulkProposalsResponse = {
  added: [1, 2, 3],
  skipped: [
    { candidate_id: 4, reason: "already_in_job" },
    { candidate_id: 5, reason: "client_nda" },
    { candidate_id: 6, reason: "client_nda" },
  ],
  warnings: [
    { candidate_id: 1, reason: "current_employment" },
    { candidate_id: 2, reason: "excluded_by_candidate" },
  ],
  total_added: 3,
  total_skipped: 3,
};

describe("summarizeBulkResult", () => {
  it("labels a hiring-manager veto instead of leaving it blank", () => {
    const withVeto: BulkProposalsResponse = {
      added: [],
      skipped: [{ candidate_id: 9, reason: "rejected_by_hiring_manager" }],
      warnings: [],
      total_added: 0,
      total_skipped: 1,
    };
    expect(summarizeBulkResult(withVeto).skipped).toEqual([
      { label: "hiring manager odrzucił po rozmowie", count: 1 },
    ]);
  });

  it("tallies skipped rows by reason with PL labels", () => {
    const s = summarizeBulkResult(resp);
    expect(s.added).toBe(3);
    expect(s.skipped).toEqual([
      { label: "już w rekrutacji", count: 1 },
      { label: "konflikt: NDA z klientem", count: 2 },
    ]);
  });

  it("tallies warnings by reason", () => {
    const s = summarizeBulkResult(resp);
    expect(s.warnings).toEqual([
      { label: "obecne zatrudnienie u klienta", count: 1 },
      { label: "kandydat wykluczył klienta", count: 1 },
    ]);
  });

  it("handles a missing warnings field", () => {
    const s = summarizeBulkResult({
      added: [1],
      skipped: [],
      total_added: 1,
      total_skipped: 0,
    });
    expect(s.warnings).toEqual([]);
    expect(s.skipped).toEqual([]);
  });
});

describe("formatReasonCounts", () => {
  it("formats as 'N× label' joined by commas", () => {
    expect(
      formatReasonCounts([
        { label: "już w rekrutacji", count: 1 },
        { label: "konflikt: NDA z klientem", count: 2 },
      ]),
    ).toBe("1× już w rekrutacji, 2× konflikt: NDA z klientem");
  });

  it("empty → empty string", () => {
    expect(formatReasonCounts([])).toBe("");
  });
});
