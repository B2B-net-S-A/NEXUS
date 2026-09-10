import { fireEvent, render, screen } from "@testing-library/react";
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

test("unknown billing is explicit and is not rendered as zero dollars", () => {
  render(<FullCandidateSearchStatus data={{ ...page, metrics: { elapsed_ms: 12345, cost_complete: false, known_cost_usd: 0 } }} offset={0} onPage={vi.fn()} />);
  expect(screen.getByText(/Czas przeglądu: 12.3 s/)).toHaveTextContent("Koszt API niepełny");
  expect(screen.queryByText(/0.000000 USD/)).not.toBeInTheDocument();
});

test("observed usage with configured pricing shows estimated API cost", () => {
  render(<FullCandidateSearchStatus data={{ ...page, metrics: { elapsed_ms: 1000, cost_complete: true, estimated_cost_usd: 0.000246 } }} offset={0} onPage={vi.fn()} />);
  expect(screen.getByText(/Szacowany koszt API: 0.000246 USD/)).toBeVisible();
});


test("shows primary exclusion totals without treating missing proof as confirmed failure", () => {
  render(<FullCandidateSearchStatus data={{ ...page, counts: { ...page.counts, exclusion_reasons: { over_budget: 3, missing_must: 5, unknown: 2, remote_only: 0 } } }} offset={0} onPage={vi.fn()} />);
  expect(screen.getByText("Powyżej budżetu: 3")).toBeVisible();
  // Default policy (10.09): a KNOWN technology gap hides, not "missing proof".
  expect(screen.getByText("Brak technologii must-have w profilu: 5")).toBeVisible();
  expect(screen.getByText("Brak zapisanej szczegółowej przyczyny: 2")).toBeVisible();
  expect(screen.queryByText("Wyłącznie praca zdalna: 0")).not.toBeInTheDocument();
});

test("a failed scan reads as interrupted with a way to start again, never as a finished empty review", () => {
  const onRestart = vi.fn();
  render(<FullCandidateSearchStatus data={{ ...page, state: "failed", error_code: "candidate_erased", counts: { ...page.counts, evaluated: 42000 } }} offset={0} onPage={vi.fn()} onRestart={onRestart} />);
  expect(screen.getByRole("status")).toHaveTextContent("Przegląd przerwany — z bazy usunięto kandydata objętego tym przeglądem");
  expect(screen.queryByText(/Przegląd zakończony/)).not.toBeInTheDocument();
  expect(screen.getByText(/Sprawdzono 42000 z 60000/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Następna" })).not.toBeInTheDocument();
  expect(screen.queryByText(/widoczni po filtrach/)).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Uruchom ponownie" }));
  expect(onRestart).toHaveBeenCalledOnce();
});

test("an unknown failure code still explains the interruption", () => {
  render(<FullCandidateSearchStatus data={{ ...page, state: "failed", error_code: "ValueError" }} offset={0} onPage={vi.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent("Przegląd przerwany — nie udało się dokończyć przeglądu bazy");
  expect(screen.queryByText("ValueError")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Uruchom ponownie" })).not.toBeInTheDocument();
});
