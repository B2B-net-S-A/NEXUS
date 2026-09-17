import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AISettingsPage from "./page";

/**
 * Panel Ustawienia → AI po decyzji z 17.09.2026: NEXUS nie ma limitów AI.
 * Ekran jest raportem zużycia i kosztu (model per funkcja, tokeny, koszt) plus
 * alarm wydatków. Test pilnuje, że przełączniki i edytor limitu nie wracają.
 */

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  testAlert: vi.fn(),
  autoMatch: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  aiSettingsApi: {
    get: mocks.get,
    testAlert: mocks.testAlert,
    autoMatch: mocks.autoMatch,
  },
}));

const RESPONSE = {
  master_enabled: true,
  features: [
    {
      feature: "cv_generator",
      enabled: true,
      monthly_limit: 0,
      model: "claude-sonnet-4-6",
      label: "Generator CV B2B",
      data_sent_to_ai: ["Treść CV"],
    },
    {
      feature: "cv_parser",
      enabled: true,
      monthly_limit: 100,
      model: "claude-sonnet-5",
      label: "Tworzenie kandydata z CV",
      data_sent_to_ai: ["Treść CV"],
    },
  ],
  usage: [
    {
      feature: "cv_generator",
      used: 12,
      input_tokens: 34_000,
      provider_calls: 2,
      output_tokens: 8_000,
      estimated_cost_usd: 1.25,
      limit: 0,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
    },
    {
      feature: "cv_parser",
      used: 3,
      input_tokens: 0,
      output_tokens: 0,
      limit: 100,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
    },
  ],
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AISettingsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ data: RESPONSE });
  mocks.autoMatch.mockResolvedValue({
    data: {
      enabled: true,
      dry_run: true,
      min_score: 70,
      max_jobs_per_candidate: 3,
      max_candidates_per_job: 10,
      decisions_7d: { added: 2, below_threshold: 5 },
      queue_7d: { done: 4, pending: 1 },
      recent: [
        {
          candidate_id: 11,
          job_id: 7,
          job_title: "Python Developer",
          score: 86.4,
          decision: "dry_run",
          reason: null,
          trigger: "cv_upload",
          created_at: "2026-09-17T10:00:00Z",
        },
      ],
    },
  });
});

describe("Panel Ustawienia → AI", () => {
  it("nie pokazuje żadnych przełączników ani limitów", async () => {
    renderPage();
    await screen.findByText("Generator CV B2B");
    expect(screen.getByText(/działają bez limitów/)).toBeInTheDocument();
    expect(screen.queryAllByRole("switch")).toHaveLength(0);
    expect(screen.queryByText(/Limit miesięczny/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Limit wyczerpany/)).not.toBeInTheDocument();
  });

  it("sumuje szacunkowy koszt miesiąca", async () => {
    renderPage();
    await screen.findByText("Generator CV B2B");
    expect(screen.getByTestId("ai-total-cost").textContent).toContain("1.25 USD");
  });

  it("renderuje model funkcji z rejestru backendu", async () => {
    renderPage();
    await screen.findByText("Generator CV B2B");
    const models = screen.getAllByTestId("feature-model").map((el) => el.textContent);
    expect(models).toContain("claude-sonnet-4-6");
    expect(models).toContain("claude-sonnet-5");
  });

  it("odróżnia zmierzone tokeny od braku pomiaru", async () => {
    renderPage();
    await screen.findByText("Generator CV B2B");
    const tokenLines = screen.getAllByTestId("feature-tokens");
    // Tylko cv_generator ma niezerowe tokeny; cv_parser (0/0) nie renderuje linii.
    expect(tokenLines).toHaveLength(2);
    expect(tokenLines[1].textContent).toContain("Brak zmierzonych odpowiedzi");
    expect(tokenLines[0].textContent).toMatch(/34\D?000/);
  });

  it("403 renderuje odmowę, nie awarię (UAT A-B04)", async () => {
    mocks.get.mockRejectedValue({ response: { status: 403 } });
    renderPage();
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(
      screen.queryByText("Nie udało się załadować raportu zużycia AI."),
    ).not.toBeInTheDocument();
  });

  it("pokazuje dziennik automatycznych dopasowań i tryb próbny", async () => {
    renderPage();
    expect(await screen.findByText("Python Developer")).toBeInTheDocument();
    expect(screen.getByTestId("auto-match-state").textContent).toContain("Tryb próbny");
    expect(screen.getByText("tryb próbny (bez dodania)")).toBeInTheDocument();
  });
});
