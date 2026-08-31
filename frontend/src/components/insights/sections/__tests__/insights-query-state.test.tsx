/**
 * Sekcje raportowe: awaria ≠ „Brak danych.” i ≠ pusty DOM (audyt F-20).
 *
 * Sześć sekcji dzieliło jedną lukę: kit (`_shared.tsx`) miał `LoadingSpinner`,
 * ale nie miał NIC na awarię. Efekt: `if (!data) return null`
 * InviteLinksSection) albo zdanie o rekrutacji zamiast zdania
 * o systemie (ActivityHeatmap, InviteLinksSection).
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
