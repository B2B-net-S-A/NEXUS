import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { CandidateSearchPage } from "@/lib/full-candidate-search-api";
import { FullCandidateSearchStatus } from "./FullCandidateSearchStatus";

const page: CandidateSearchPage = {
  run_id: "r", state: "partial", versions: {}, results: [],
  counts: { population: 60000, pending: 0, evaluated: 59999, failed: 1, eligible: 100, excluded: 59899, needs_verification: 3 },
  ranking_complete: false, data_changed: true, brief_status: "title_only", next_offset: 20, total_after_threshold: 100,
};

test("reports incomplete coverage and stale/title-only evidence without promising best matches", () => {
  render(<FullCandidateSearchStatus data={page} offset={0} onPage={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent("59999 z 60000");
  expect(screen.getByRole("status")).toHaveTextContent("Nie udało się ocenić: 1");
  expect(screen.getByText(/Ranking nie jest kompletny/)).toBeVisible();
  expect(screen.getByText(/Dane zmieniły się/)).toBeVisible();
  expect(screen.getByText(/Ocena wstępna/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Poprzednia" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Następna" })).toBeEnabled();
});

test("active scan exposes progress, not an empty completed ranking", () => {
  render(<FullCandidateSearchStatus data={{ ...page, state: "running", counts: { ...page.counts, pending: 30000 } }} offset={0} onPage={vi.fn()} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("value", "30000");
  expect(screen.queryByRole("button", { name: "Następna" })).not.toBeInTheDocument();
});
