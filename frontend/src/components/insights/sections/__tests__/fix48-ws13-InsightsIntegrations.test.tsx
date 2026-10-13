import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { IntegrationsSummary } from "@/lib/integrations-api";
import { InsightsIntegrations } from "@/components/insights/sections/InsightsIntegrations";

// Traffit wyłączony na stałe 14.10.2026: runner JJIT nie zakłada już kandydatów
// w Traffit, więc etykiety statystyk nie mogą sugerować bieżącego zapisu tam.
// Dane bez zmian — zmieniają się tylko podpisy.

const totals = {
  runs: 3,
  runs_failed: 0,
  created: 12,
  duplicates: 4,
  cv_refreshed: 0,
  errors: 0,
  skipped: 0,
  nexus_pushed: 12,
  nexus_created: 8,
  nexus_existing: 4,
  nexus_jobs: 5,
  nexus_errors: 0,
};

const summary: IntegrationsSummary = {
  days: 30,
  generated_at: "2026-10-14T08:00:00Z",
  sources: [
    {
      source: "jjit",
      label: "JustJoin.IT",
      last_run: {
        id: 1,
        source: "jjit",
        mode: "import",
        status: "ok",
        started_at: "2026-10-14T06:00:00Z",
        finished_at: "2026-10-14T06:05:00Z",
        host: null,
        version: null,
        stats: { created: 7, duplicates: 0, nexus_jobs: 3, errors: 0 },
        error: null,
      },
      last_success_at: "2026-10-14T06:05:00Z",
      stale: false,
      stale_after_hours: 26,
      totals,
      daily: [],
    },
  ],
  recent_errors: [],
  top_jobs: [],
};

vi.mock("@/lib/integrations-api", () => ({
  integrationsApi: { summary: vi.fn(async () => summary) },
}));

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <InsightsIntegrations />
    </QueryClientProvider>,
  );
}

describe("InsightsIntegrations po wyłączeniu Traffita", () => {
  it("nie podpisuje bieżących liczb jako zapisu do Traffita", async () => {
    renderSection();

    expect(await screen.findByText("Nowi kandydaci")).toBeInTheDocument();
    expect(screen.queryByText("Nowi w Traffit")).not.toBeInTheDocument();
    expect(screen.getByText("Duplikaty (znani w Traffit do 14.10.2026)")).toBeInTheDocument();
    expect(screen.queryByText("Duplikaty (znani w Traffit)")).not.toBeInTheDocument();
  });
});
