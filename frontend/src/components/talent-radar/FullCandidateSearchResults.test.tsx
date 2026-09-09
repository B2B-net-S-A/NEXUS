import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { CandidateSearchPage } from "@/lib/full-candidate-search-api";
import { FullCandidateSearchResults } from "./FullCandidateSearchResults";

const data: CandidateSearchPage = {
  run_id: "r", state: "partial", versions: {},
  counts: { population: 60000, pending: 0, failed: 0, evaluated: 60000, eligible: 100, excluded: 59900, needs_verification: 1 },
  total_after_threshold: 100, next_offset: 20, ranking_complete: false,
  results: [{ candidate: { id: 4, name: "Anna", lastname: "Testowa", location: null, competence_category: null, years_it_experience: null, availability_status: null, champion: false, avatar_url: null },
    fit_score: null, measurement: "missing_index", match: null, eligibility: null,
    requirements: [{ any_of: ["python", "java"], level: "must", status: "unknown", matched: [], candidate_updated_at: "2026-09-09" }],
  }],
};

test("unknown assessment remains visible without zero points or proof of missing skill", () => {
  const onPage = vi.fn();
  render(<FullCandidateSearchResults data={data} error={null} loading={false} fetching={false} offset={0} onPage={onPage} onRetry={vi.fn()} canOpenProfile={false} />);
  expect(screen.getByText("Anna Testowa")).toBeVisible();
  expect(screen.getByText("Ocena niepełna")).toBeVisible();
  expect(screen.getByText(/python lub java.*brak potwierdzenia/)).toBeVisible();
  expect(screen.queryByText(/0[,.]0\/100/)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Otwórz profil" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Następna" }));
  expect(onPage).toHaveBeenCalledWith(20);
});

test("failed page read does not present old results as current", () => {
  const onRetry = vi.fn();
  render(<FullCandidateSearchResults data={data} error={new Error("Sieć niedostępna")} loading={false} fetching={false} offset={0} onPage={vi.fn()} onRetry={onRetry} canOpenProfile />);
  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.queryByText("Anna Testowa")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
  expect(onRetry).toHaveBeenCalledOnce();
});

test("profile skill signal does not claim verified proficiency or date", () => {
  const signal = structuredClone(data);
  signal.results[0].requirements[0] = {
    ...signal.results[0].requirements[0], status: "met", matched: ["python"],
    evidence_basis: "profile_signal", verified_at: null, usage_context: null,
  };
  render(<FullCandidateSearchResults data={signal} error={null} loading={false} fetching={false} offset={0} onPage={vi.fn()} onRetry={vi.fn()} canOpenProfile />);
  expect(screen.getByText(/sygnał w profilu — do weryfikacji/)).toBeVisible();
  expect(screen.queryByText(/potwierdzone/)).not.toBeInTheDocument();
});


test("verification action requires a saved recruitment and write permission", () => {
  const props = { data, error: null, loading: false, fetching: false, offset: 0, onPage: vi.fn(), onRetry: vi.fn(), canOpenProfile: true, onVerified: vi.fn() };
  const view = render(<FullCandidateSearchResults {...props} canVerify />);
  expect(screen.queryByRole("button", { name: "Zweryfikuj wymaganie" })).not.toBeInTheDocument();
  view.rerender(<FullCandidateSearchResults {...props} jobId={7} canVerify={false} />);
  expect(screen.queryByRole("button", { name: "Zweryfikuj wymaganie" })).not.toBeInTheDocument();
  view.rerender(<FullCandidateSearchResults {...props} jobId={7} canVerify />);
  expect(screen.getByRole("button", { name: "Zweryfikuj wymaganie" })).toBeVisible();
});
