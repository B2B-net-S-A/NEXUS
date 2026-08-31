/**
 * Sekcje raportowe: awaria ≠ „Brak danych.” i ≠ pusty DOM (audyt F-20).
 *
 * Sześć sekcji dzieliło jedną lukę: kit (`_shared.tsx`) miał `LoadingSpinner`,
 * ale nie miał NIC na awarię. Efekt: `if (!data) return null` (BoardKPI,
 * InviteLinksSection) albo zdanie o rekrutacji zamiast zdania
 * o systemie (FunnelSection, TimeToHireSection, ActivityHeatmap).
 *
 * Testy odrzucają obietnice API, czyli idą tą samą ścieżką co defekt.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  board: vi.fn(),
  sales: vi.fn(),
  funnel: vi.fn(),
  timeToHire: vi.fn(),
  leaderboard: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.leaderboard(...args) },
  reportsApi: {
    board: (...args: unknown[]) => mocks.board(...args),
    sales: (...args: unknown[]) => mocks.sales(...args),
  },
  phase3Api: {
    funnel: (...args: unknown[]) => mocks.funnel(...args),
    timeToHire: (...args: unknown[]) => mocks.timeToHire(...args),
  },
}));

import { ActivityHeatmap } from "@/components/insights/sections/ActivityHeatmap";
import { BoardKPI } from "@/components/insights/sections/BoardKPI";
import { FunnelSection } from "@/components/insights/sections/FunnelSection";
import { TimeToHireSection } from "@/components/insights/sections/TimeToHireSection";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderSection(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

describe("sekcje insights — awaria zapytania", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("BoardKPI pokazuje ostrzeżenie, gdy KPI finansowe pomijają brakujący kurs", async () => {
    mocks.board.mockResolvedValue({
      data: {
        recruitment: { placements_ytd: 0, funnel_efficiency_avg: 0 },
        sales: {
          revenue_ytd: 0,
          margin_ytd: 0,
          active_consultants: 0,
          active_contracts: 0,
        },
        delivery: { avg_hit_ratio: 0, top_dl: "—" },
        tenders: { total: 0, win_rate: 0 },
        headcount: { total_users: 0, total_candidates: 0 },
        trends: [],
        finance_quality: "unavailable",
        finance_warnings: ["Brak kursu NBP dla walut: GBP"],
      },
    });

    renderSection(<BoardKPI />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Brak kursu NBP dla walut: GBP",
    );
  });

  it("BoardKPI przy 500 mówi o awarii zamiast znikać z ekranu", async () => {
    mocks.board.mockRejectedValue(httpError(500));

    const { container } = renderSection(<BoardKPI />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji „Board KPI"/),
    ).toBeInTheDocument();
    // Przed naprawą `if (!data) return null` zostawiał pusty DOM.
    expect(container).not.toBeEmptyDOMElement();
  });

  it("BoardKPI przy 403 nie proponuje ponowienia, tylko tłumaczy uprawnienia", async () => {
    mocks.board.mockRejectedValue(httpError(403));

    renderSection(<BoardKPI />);

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.getByText(/Dane NIE są puste/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Spróbuj ponownie/ }),
    ).not.toBeInTheDocument();
  });

  it("FunnelSection przy awarii NIE pisze „Brak danych.”", async () => {
    mocks.funnel.mockRejectedValue(httpError(500));

    renderSection(<FunnelSection />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak danych.")).not.toBeInTheDocument();
  });

  it("FunnelSection przy pustym lejku dalej pisze „Brak danych.”", async () => {
    mocks.funnel.mockResolvedValue({ data: { funnel: [] } });

    renderSection(<FunnelSection />);

    expect(await screen.findByText("Brak danych.")).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie udało się pobrać danych sekcji/),
    ).not.toBeInTheDocument();
  });

  it("TimeToHireSection przy awarii nie twierdzi „łącznie 0 zatrudnień”", async () => {
    mocks.timeToHire.mockRejectedValue(httpError(500));

    renderSection(<TimeToHireSection />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Brak zatrudnień w okresie/)).not.toBeInTheDocument();
    expect(screen.queryByText(/łącznie 0 zatrudnień/)).not.toBeInTheDocument();
  });

  it("ActivityHeatmap przy awarii nie mówi „Brak danych dla wybranego okresu”", async () => {
    mocks.leaderboard.mockRejectedValue(httpError(500));

    renderSection(<ActivityHeatmap period="month" />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak danych dla wybranego okresu"),
    ).not.toBeInTheDocument();
  });

  it("ActivityHeatmap przy pustym okresie dalej pokazuje pusty stan", async () => {
    mocks.leaderboard.mockResolvedValue({ data: { leaderboard: [] } });

    renderSection(<ActivityHeatmap period="month" />);

    expect(
      await screen.findByText("Brak danych dla wybranego okresu"),
    ).toBeInTheDocument();
  });
});
