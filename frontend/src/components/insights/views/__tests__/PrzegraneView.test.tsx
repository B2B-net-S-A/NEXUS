/**
 * Zakładka „Przegrane” (25.11.2026): fakty z serwera, „Dlaczego?” zapisuje się od
 * razu, filtr DL, awaria nie wygląda jak pusty okres, a rady AI to dodatek.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LostReviewResponse } from "@/lib/lost-review";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  saveWhy: vi.fn(),
  aiSummary: vi.fn(),
  addLesson: vi.fn(),
  archiveLesson: vi.fn(),
  clientQuestion: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/insights",
}));

vi.mock("@/components/insights/useInsightsPeriod", () => ({
  useInsightsPeriod: (fallback: unknown) => ({ period: fallback, setPeriod: vi.fn() }),
}));

vi.mock("@/components/insights/PeriodPicker", () => ({
  PeriodPicker: () => <div data-testid="period-picker" />,
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.showSuccess, showError: mocks.showError }),
}));

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div style={{ width: 600, height: 300 }}>{children}</div>
    ),
  };
});

vi.mock("@/lib/lost-review", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/lost-review")>();
  return {
    ...actual,
    lostReviewApi: {
      get: (...a: unknown[]) => mocks.get(...a),
      saveWhy: (...a: unknown[]) => mocks.saveWhy(...a),
      aiSummary: (...a: unknown[]) => mocks.aiSummary(...a),
      addLesson: (...a: unknown[]) => mocks.addLesson(...a),
      archiveLesson: (...a: unknown[]) => mocks.archiveLesson(...a),
      clientQuestion: (...a: unknown[]) => mocks.clientQuestion(...a),
      clientRules: vi.fn(),
    },
  };
});

import { PrzegraneView } from "@/components/insights/views/PrzegraneView";

const SIDE = { count: 2, first_cv_days: 3.5, cvs: 5, interview_share: 83 };

const DATA: LostReviewResponse = {
  period: { kind: "month", start: "2026-11-01T00:00:00+01:00", end: "2026-12-01T00:00:00+01:00" },
  period_label: "listopad 2026",
  since: "2026-10-11T22:00:00+00:00",
  counts: { won: 1, lost: 2, competitor: 1, idle: 1 },
  hit_ratio: 33.3,
  known: 1,
  why_filled: 0,
  stages: { no_cv: 0, cv_only: 1, interview: 1, acceptance: 0 },
  compare: { won: SIDE, lost: { ...SIDE, first_cv_days: 4.1, interview_share: 50 } },
  trend: [{ month: "2026-11", label: "lis 26", won: 1, lost: 2, hit_ratio: 33.3 }],
  why_counts: [],
  source_counts: { client: 0, ours: 0, unknown: 0 },
  client_verdicts: [{ label: "Za mało doświadczenia", count: 2 }],
  clients: [
    {
      client_id: 11,
      name: "Bank Testowy",
      won: 1,
      lost: 2,
      idle: 1,
      hit_ratio: 33.3,
      stages: { no_cv: 0, cv_only: 1, interview: 1, acceptance: 0 },
      pattern: "CV nie przechodzą do rozmów",
      verdicts: [{ label: "Za mało doświadczenia", count: 2 }],
      why: [],
      lessons: [],
    },
  ],
  jobs: [
    {
      job_id: 101,
      title: "Analityk testowy",
      client_id: 11,
      client_name: "Bank Testowy",
      dl_id: 5,
      dl_name: "DL Pierwszy",
      outcome: "competitor",
      stage: "interview",
      closed_at: "2026-11-20T10:00:00+00:00",
      days_open: 30,
      days_first_cv: 2.5,
      cvs: 4,
      interviews: 1,
      client_verdicts: ["Za mało doświadczenia", "Za mało doświadczenia"],
      notes: null,
      why: [],
      source: null,
      ask_pending: false,
    },
    {
      job_id: 102,
      title: "Tester testowy",
      client_id: 11,
      client_name: "Bank Testowy",
      dl_id: 6,
      dl_name: "DL Drugi",
      outcome: "idle",
      stage: "cv_only",
      closed_at: "2026-11-21T10:00:00+00:00",
      days_open: 40,
      days_first_cv: 6,
      cvs: 3,
      interviews: 0,
      client_verdicts: [],
      notes: null,
      why: [],
      source: null,
      ask_pending: false,
    },
  ],
  lessons: [],
  findings: ["Przegrywamy na przejściu z CV do rozmowy: rozmowę u klienta miało 50% przegranych i 83% wygranych."],
};

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PrzegraneView />
    </QueryClientProvider>,
  );
}

describe("PrzegraneView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue(DATA);
    mocks.saveWhy.mockResolvedValue({ job_id: 101, why: ["competitor_cheaper"], source: null });
  });

  it("pokazuje liczby okresu, wnioski z liczb i karty przegranych", async () => {
    renderView();
    expect(await screen.findByText(/Listopad 2026\. Przegrana/)).toBeInTheDocument();
    expect(screen.getByTestId("lost-review-findings")).toHaveTextContent("50% przegranych i 83% wygranych");
    expect(screen.getAllByTestId("lost-review-job")).toHaveLength(2);
    expect(screen.getByText("Klient o naszych: Za mało doświadczenia ×2")).toBeInTheDocument();
    expect(screen.getByText("klient nie ocenił nikogo z naszych")).toBeInTheDocument();
    expect(screen.getByText("NEXUS zamknął po 28 dniach")).toBeInTheDocument();
  });

  it("„Dlaczego?” zapisuje się od razu", async () => {
    renderView();
    const card = (await screen.findAllByTestId("lost-review-job"))[0];
    fireEvent.click(within(card).getByRole("button", { name: "Konkurent tańszy" }));
    await waitFor(() =>
      expect(mocks.saveWhy).toHaveBeenCalledWith(101, { why: ["competitor_cheaper"], source: null }),
    );
  });

  it("wpisany wniosek zostaje po kliknięciu „Dlaczego?” i odświeżeniu danych", async () => {
    renderView();
    const card = (await screen.findAllByTestId("lost-review-job"))[0];
    const input = within(card).getByLabelText("Co zmieniamy?");
    fireEvent.change(input, { target: { value: "Pierwsze CV do 48 h" } });
    mocks.get.mockResolvedValue({
      ...DATA,
      jobs: [{ ...DATA.jobs[0], why: ["competitor_cheaper"] }, DATA.jobs[1]],
    });
    fireEvent.click(within(card).getByRole("button", { name: "Konkurent tańszy" }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    const after = (await screen.findAllByTestId("lost-review-job"))[0];
    expect(within(after).getByLabelText("Co zmieniamy?")).toHaveValue("Pierwsze CV do 48 h");
    expect(within(after).getByRole("button", { name: "Konkurent tańszy" })).toHaveAttribute("aria-pressed", "true");
  });

  it("drugi klik w trakcie zapisu czeka i wysyła tylko ostatni wybór", async () => {
    let release: (v: unknown) => void = () => {};
    mocks.saveWhy.mockImplementationOnce(() => new Promise((r) => (release = r)));
    renderView();
    const card = (await screen.findAllByTestId("lost-review-job"))[0];
    fireEvent.click(within(card).getByRole("button", { name: "Konkurent tańszy" }));
    fireEvent.click(within(card).getByRole("button", { name: "Konkurent był szybszy" }));
    fireEvent.click(within(card).getByRole("button", { name: "Za mało CV / brak ludzi" }));
    await waitFor(() => expect(mocks.saveWhy).toHaveBeenCalledTimes(1));
    release({ job_id: 101, why: ["competitor_cheaper"], source: null });
    await waitFor(() => expect(mocks.saveWhy).toHaveBeenCalledTimes(2));
    expect(mocks.saveWhy).toHaveBeenLastCalledWith(101, {
      why: ["competitor_faster", "too_few_cvs"],
      source: null,
    });
  });

  it("filtr DL zawęża listę", async () => {
    renderView();
    await screen.findAllByTestId("lost-review-job");
    fireEvent.click(screen.getByRole("button", { name: "DL Drugi" }));
    const cards = screen.getAllByTestId("lost-review-job");
    expect(cards).toHaveLength(1);
    expect(cards[0]).toHaveTextContent("Tester testowy");
  });

  it("awaria odczytu nie wygląda jak okres bez przegranych", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("HTTP 500"), { response: { status: 500 } }));
    renderView();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByText(/Ładowanie|Przegrane$/)).toBeNull());
    expect(screen.queryByText("W tym okresie nie ma przegranych rekrutacji.")).toBeNull();
    expect(screen.queryByTestId("lost-review-list")).toBeNull();
  });

  it("błąd rad AI zostawia wnioski z liczb", async () => {
    mocks.aiSummary.mockRejectedValue(
      Object.assign(new Error("HTTP 422"), {
        response: { status: 422, data: { detail: { code: "lost_review_ai_failed", message: "Nie udało się przygotować wniosków AI." } } },
      }),
    );
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: /Poproś o rady AI/ }));
    expect(await screen.findByText(/Nie udało się przygotować wniosków AI/)).toBeInTheDocument();
    expect(screen.getByTestId("lost-review-findings")).toBeInTheDocument();
  });
});
