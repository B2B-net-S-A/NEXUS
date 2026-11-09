import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const jobLatest = vi.fn();
const startRun = vi.fn();
const feedback = vi.fn();
vi.mock("@/lib/duty-search-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/duty-search-api")>();
  return {
    ...actual,
    dutySearchApi: {
      jobLatest: (...args: unknown[]) => jobLatest(...args),
      start: (...args: unknown[]) => startRun(...args),
      run: vi.fn(),
      feedback: (...args: unknown[]) => feedback(...args),
    },
  };
});
const bulkAdd = vi.fn();
vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...args: unknown[]) => bulkAdd(...args) },
}));
const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showSuccess, showError }) }));

import { DutySearchWorkspace } from "@/components/duty-search/DutySearchWorkspace";
import type { DutyRun } from "@/lib/duty-search-api";

const USAGE = { used_today: 2, daily_limit: 10 };

function run(over: Partial<DutyRun> = {}): DutyRun {
  return {
    run_id: "r1",
    state: "complete",
    error_code: null,
    job_id: 7,
    client_id: 3,
    title: "Release manager",
    goal: "Zarządzanie release i change management w banku.",
    created_at: "2026-11-09T20:00:00Z",
    completed_at: "2026-11-09T20:02:00Z",
    plan: {
      summary: "prowadzili change i release management w banku",
      capabilities: [{ name: "Release management", weight: 3, hint: "" }],
      signals: [],
      anti: [],
    },
    stats: { judged: 90, seconds: 110, tiers: {}, plan_ok: true, canonical_degraded: false, judge_errors: 0 },
    results: [
      {
        candidate_id: 11,
        name: "Anna K",
        position: "Release Manager",
        years_it: 9,
        tier: "zrobil_to",
        confidence: 92,
        fit_score: 70,
        from_goal_only: false,
        capabilities: { "Release management": "tak" },
        evidence: [{ quote: "Planning and coordinating releases to production", where: "IBM", meaning: "Prowadził release." }],
        gap: "",
        question: "Jak wyglądał CAB?",
        error: null,
        feedback: null,
      },
      {
        candidate_id: 12,
        name: "Piotr N",
        position: "Tester",
        years_it: 4,
        tier: "brak",
        confidence: null,
        fit_score: null,
        from_goal_only: true,
        capabilities: {},
        evidence: [],
        gap: "",
        question: "",
        error: null,
        feedback: null,
      },
    ],
    usage: USAGE,
    ...over,
  };
}

function renderJob() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
      <DutySearchWorkspace jobId={7} />
    </QueryClientProvider>,
  );
}

describe("DutySearchWorkspace (rekrutacja)", () => {
  beforeEach(() => {
    jobLatest.mockReset();
    startRun.mockReset();
    bulkAdd.mockReset();
    showError.mockReset();
  });

  it("bez przebiegu pokazuje obowiązki z Championa i startuje wyszukiwanie", async () => {
    jobLatest.mockResolvedValue({ has_duties: true, duties: "Zarządzanie release i change management w banku.", title: "Release manager", run: null, usage: USAGE });
    startRun.mockResolvedValue({ run_id: "r2", state: "queued", usage: USAGE });
    renderJob();
    const field = (await screen.findByLabelText("Obowiązki z Championa")) as HTMLTextAreaElement;
    expect(field.value).toContain("change management");
    fireEvent.click(screen.getByRole("button", { name: /Szukaj, kto już to robił/ }));
    await waitFor(() => expect(startRun).toHaveBeenCalledWith({ job_id: 7, goal: undefined }));
  });

  it("awaria przebiegu to komunikat z ponowieniem, nie pusta lista", async () => {
    jobLatest.mockResolvedValue({ has_duties: true, duties: "x".repeat(40), title: "R", run: run({ state: "failed", error_code: "judge_unavailable", results: [] }), usage: USAGE });
    renderJob();
    const alert = await screen.findByTestId("duty-search-failed");
    expect(alert.textContent).toContain("AI nie odpowiedziało");
    expect(within(alert).getByRole("button", { name: /Uruchom ponownie/ })).toBeTruthy();
    expect(screen.queryByText(/nie znalazło w przeczytanych CV/)).toBeNull();
  });

  it("trwający przebieg pokazuje postęp", async () => {
    jobLatest.mockResolvedValue({ has_duties: true, duties: "x".repeat(40), title: "R", run: run({ state: "running", results: [] }), usage: USAGE });
    renderJob();
    expect(await screen.findByTestId("duty-search-running")).toBeTruthy();
  });

  it("wynik: poziom z cytatem, osoby bez dowodu schowane, dodanie do Nowych", async () => {
    jobLatest.mockResolvedValue({ has_duties: true, duties: "x".repeat(40), title: "R", run: run(), usage: USAGE });
    bulkAdd.mockResolvedValue({ added: [11], skipped: [], total_added: 1, total_skipped: 0 });
    renderJob();
    const cards = await screen.findAllByTestId("duty-result");
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("Robił to");
    expect(cards[0].textContent).toContain("Planning and coordinating releases");
    expect(screen.getByText(/Dziś: 2 z 10/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /osoby bez dowodu celu \(1\)/ }));
    expect(screen.getAllByTestId("duty-result")).toHaveLength(2);
    fireEvent.click(within(cards[0]).getByRole("button", { name: /Dodaj do Nowych/ }));
    await waitFor(() =>
      expect(bulkAdd).toHaveBeenCalledWith(7, { candidate_ids: [11], source: "duty_search" }),
    );
    expect(await within(cards[0]).findByRole("button", { name: /Dodano/ })).toBeTruthy();
  });
});
