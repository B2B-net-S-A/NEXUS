import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CandidateSearchPage } from "@/lib/full-candidate-search-api";
import { mergeProposals, type ProposalEntry } from "@/lib/proposals-merge";

const mocks = vi.hoisted(() => ({ state: { current: {} as Record<string, unknown> }, push: vi.fn() }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/components/v2/recruitment/useJobProposals", () => ({ useJobProposals: () => mocks.state.current }));
vi.mock("@/components/v2/recruitment/useCanAddToRecruitment", () => ({ useCanAddToRecruitment: () => true }));
vi.mock("@/components/talent-radar/RequirementVerificationDialog", () => ({
  useCanVerifyRequirements: () => false,
  RequirementVerificationDialog: () => null,
}));
// Tabela ma własne testy; tu liczy się to, co segment jej PODAJE.
vi.mock("@/components/v2/recruitment/PeopleTable", () => ({
  PeopleTable: ({ rows, empty, footer, loading, onSelectionChange }: { rows: Array<{ key: string; fullName: string }>; empty: React.ReactNode; footer: React.ReactNode; loading: boolean; onSelectionChange: (s: Set<string>) => void }) => (
    <div data-testid="people-table">
      {loading && <p>Wczytuję…</p>}
      {rows.length === 0 ? <div data-testid="empty">{empty}</div> : rows.map((r) => <p key={r.key}>{r.fullName}</p>)}
      <button type="button" onClick={() => onSelectionChange(new Set(rows.map((r) => r.key)))}>zaznacz wszystkich (mock)</button>
      <div data-testid="footer">{footer}</div>
    </div>
  ),
}));

import { ProposalsSegment } from "@/components/v2/recruitment/ProposalsSegment";

function page(over: Partial<CandidateSearchPage> = {}): CandidateSearchPage {
  return {
    run_id: "run-1", state: "complete",
    counts: { population: 100, pending: 0, failed: 0, evaluated: 100, eligible: 0, excluded: 100, needs_verification: 0, exclusion_reasons: { over_budget: 60, missing_must: 40 } },
    results: [], versions: {}, ranking_complete: true, coverage_complete: true, total_after_threshold: 0,
    ...over,
  };
}

function entriesOf(ids: number[]): ProposalEntry[] {
  return mergeProposals({
    inbox: ids.map((id) => ({
      candidate: { id, name: "Anna", lastname: `Nowak${id}`, title: null, city: null, availability_status: null, availability_date: null, expected_rate_hourly: null, expected_rate_redacted: false },
      sources: ["new_cv"], score: 80 - id, evidence: null, first_seen_at: null, last_seen_at: null, is_new: false, status: "proposed" as const, eligibility: null,
    })),
  });
}

function state(over: { entries?: ProposalEntry[]; run?: Record<string, unknown>; status?: Record<string, unknown>; inbox?: Record<string, unknown>; totalBeforeFilters?: number } = {}) {
  const entries = over.entries ?? [];
  return {
    rows: entries.map((e) => e.row),
    entries,
    entryById: new Map(entries.map((e) => [e.row.candidateId, e])),
    totalBeforeFilters: over.totalBeforeFilters ?? entries.length,
    sourceCounts: { all: entries.length, full_base: 0, new_cv: entries.length, similar_projects: 0, recommendation: 0, marketplace: 0 },
    status: {
      run: { runId: null, data: undefined, error: null, running: false, starting: false, loading: false, fetching: false, needsNewRun: false, offset: 0, setOffset: vi.fn(), refresh: vi.fn(), ...over.run },
      startRun: vi.fn(), retryRun: vi.fn(), latestRun: null, engineDegraded: false,
      inbox: { total: entries.length, hidden: 0, isSuccess: true, isLoading: false, isError: false, error: null, hasMore: false, loadingMore: false, loadMore: vi.fn(), retry: vi.fn(), ...over.inbox },
      similar: { degraded: false, hiddenIneligible: 0, isError: false },
      recommendations: { degraded: false, stale: false, pending: false, isError: false, regenerate: vi.fn(), regenerating: false },
      ...over.status,
    },
    addToJob: vi.fn(), adding: false, dismiss: vi.fn(), dismissing: false, addToShortlist: vi.fn(), shortlisting: false,
  };
}

const props = { jobId: 42, budgetHourly: 150, onOpenManualSearch: vi.fn(), onOpenQuickAdd: vi.fn() };

beforeEach(() => vi.clearAllMocks());

describe("ProposalsSegment — stany", () => {
  it("bez żadnego przeglądu: zachęta do uruchomienia, a start jest jawnym kliknięciem", () => {
    const s = state();
    mocks.state.current = s;
    render(<ProposalsSegment {...props} />);
    expect(screen.getByText("Całej bazy jeszcze nie przeszukano")).toBeInTheDocument();
    expect(s.status.startRun).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByTestId("empty")).getByRole("button", { name: "Uruchom przegląd bazy" }));
    expect(s.status.startRun).toHaveBeenCalledTimes(1);
  });

  it("przegląd w toku: postęp i blokada ponownego startu", () => {
    mocks.state.current = state({ run: { runId: "run-1", running: true, data: page({ state: "running", counts: { ...page().counts, pending: 40, evaluated: 60 } }) } });
    render(<ProposalsSegment {...props} />);
    expect(screen.getByRole("progressbar", { name: "Postęp przeglądu" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Uruchom ponownie" })).toBeDisabled();
    expect(screen.getByTestId("empty")).toHaveTextContent("Przegląd bazy trwa");
  });

  it("przegląd przerwany: panel terminalny, nigdy brak propozycji", () => {
    mocks.state.current = state({ run: { runId: "run-1", needsNewRun: true, data: page({ state: "failed", error_code: "stalled" }) } });
    render(<ProposalsSegment {...props} />);
    expect(screen.getByText(/Przegląd przerwany — przegląd przestał robić postępy/)).toBeInTheDocument();
    expect(screen.getByTestId("empty")).toHaveTextContent("Przegląd bazy został przerwany");
  });

  it("awaria silnika renderuje się jako awaria, nie jako pustka", () => {
    mocks.state.current = state({ status: { engineDegraded: true } });
    render(<ProposalsSegment {...props} />);
    const alerts = screen.getAllByRole("alert");
    expect(alerts.some((a) => /Silnik dopasowań AI jest chwilowo niedostępny/.test(a.textContent ?? ""))).toBe(true);
    expect(screen.getByTestId("empty")).toHaveTextContent("To NIE znaczy, że w bazie nikogo nie ma");
  });

  it("przegląd zakończony bez dopuszczonych osób pokazuje przyczyny wykluczeń", () => {
    mocks.state.current = state({ run: { runId: "run-1", data: page() } });
    render(<ProposalsSegment {...props} />);
    const reasons = screen.getByRole("list", { name: "Przyczyny wykluczenia" });
    expect(within(reasons).getByText("Powyżej budżetu: 60")).toBeInTheDocument();
    expect(screen.getByTestId("empty")).toHaveTextContent("nie znalazł nikogo spoza rekrutacji");
  });

  it("awaria skrzynki to błąd z ponowieniem; pusty stan nie pojawia się przed isSuccess", () => {
    const s = state({ inbox: { isSuccess: false, isError: true, error: new Error("x") } });
    mocks.state.current = s;
    const { unmount } = render(<ProposalsSegment {...props} />);
    fireEvent.click(within(screen.getByTestId("empty")).getByRole("button", { name: "Spróbuj ponownie" }));
    expect(s.status.inbox.retry).toHaveBeenCalled();
    unmount();
    mocks.state.current = state({ inbox: { isSuccess: false, isLoading: true } });
    render(<ProposalsSegment {...props} />);
    expect(screen.getByTestId("empty")).toBeEmptyDOMElement();
  });

  it("filtry ukryły wszystko ≠ brak propozycji", () => {
    mocks.state.current = state({ totalBeforeFilters: 5 });
    render(<ProposalsSegment {...props} />);
    expect(screen.getByTestId("empty")).toHaveTextContent("Żadna propozycja nie pasuje do ustawionych filtrów");
  });

  it("wiersze: akcje zbiorcze działają na zaznaczonych, panel pokazuje pierwszą osobę", () => {
    const s = state({ entries: entriesOf([1, 2]) });
    mocks.state.current = s;
    render(<ProposalsSegment {...props} />);
    expect(screen.getByRole("heading", { name: "Anna Nowak1" })).toBeInTheDocument();
    const footer = within(screen.getByTestId("footer"));
    expect(footer.getByRole("button", { name: "Dodaj do rekrutacji" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "zaznacz wszystkich (mock)" }));
    fireEvent.click(footer.getByRole("button", { name: "Pomiń" }));
    expect(s.dismiss).toHaveBeenCalledWith([1, 2]);
    fireEvent.click(screen.getByRole("button", { name: "zaznacz wszystkich (mock)" }));
    fireEvent.click(footer.getByRole("button", { name: "Porównaj" }));
    expect(mocks.push).toHaveBeenCalledWith("/candidates/compare?ids=1%2C2&job=42");
  });

  it("skróty D / P działają na aktywnej osobie, ale nie w polu tekstowym", () => {
    const s = state({ entries: entriesOf([1]) });
    mocks.state.current = s;
    render(<ProposalsSegment {...props} />);
    fireEvent.keyDown(screen.getByTestId("people-table"), { key: "d" });
    expect(s.addToJob).toHaveBeenCalledWith([1]);
    fireEvent.click(screen.getByRole("button", { name: "Dopasuj kryteria" }));
    fireEvent.keyDown(screen.getByLabelText("Lokalizacja"), { key: "p" });
    expect(s.dismiss).not.toHaveBeenCalled();
  });

  it("„Dopasuj kryteria” niesie „Wymagania z requestu”; zapis wymagań kasuje zapisany przegląd (jak AI Matching)", () => {
    const clear = vi.fn();
    mocks.state.current = state({ run: { clear } });
    const renderRequirements = vi.fn(({ onSaved }: { onSaved: () => void }) => (
      <button type="button" onClick={onSaved}>zapisz wymagania (mock)</button>
    ));
    render(<ProposalsSegment {...props} renderRequirements={renderRequirements} />);
    // Zwinięte = niezamontowane: zapytanie o wymagania nie leci bez potrzeby.
    expect(renderRequirements).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Dopasuj kryteria" }));
    fireEvent.click(screen.getByRole("button", { name: "zapisz wymagania (mock)" }));
    expect(clear).toHaveBeenCalledTimes(1);
  });

  it("przyciski wyszukiwania ręcznego i dodania po nazwisku wołają rodzica", () => {
    mocks.state.current = state();
    render(<ProposalsSegment {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Szukaj ręcznie" }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj po nazwisku" }));
    expect(props.onOpenManualSearch).toHaveBeenCalled();
    expect(props.onOpenQuickAdd).toHaveBeenCalled();
  });
});
