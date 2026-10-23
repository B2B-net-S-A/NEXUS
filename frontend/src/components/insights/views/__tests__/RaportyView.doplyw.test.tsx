/**
 * Raport „Źródła, portale i linki” (audyt 22.10.2026, F77): lejek źródeł
 * czyta `/api/reports/sources` (odczyt kandydatów) — Rada nadzorcza go nie ma,
 * więc zamiast czerwonego błędu widzi krótką notkę, a reszta raportu zostaje.
 */
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/insights/sections/SourcesFunnelSection", () => ({
  SourcesFunnelSection: () => <div>lejek źródeł</div>,
}));
vi.mock("@/components/insights/sections/InsightsIntegrations", () => ({
  InsightsIntegrations: () => <div>integracje</div>,
}));
vi.mock("@/components/insights/sections/InsightsInviteLinks", () => ({
  InsightsInviteLinks: () => <div>linki</div>,
}));
vi.mock("@/components/insights/PeriodPicker", () => ({ PeriodPicker: () => null }));
vi.mock("@/components/insights/useInsightsPeriod", () => ({
  useInsightsPeriod: (fallback: unknown) => ({ period: fallback, setPeriod: vi.fn() }),
}));

import { RaportyView } from "@/components/insights/views/RaportyView";
import { useAuthStore } from "@/store/auth";

function renderAs(role: string) {
  useAuthStore.setState({ user: { id: 7, role, roles: [role] } } as never);
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RaportyView reportId="doplyw" />
    </QueryClientProvider>,
  );
}

describe("RaportyView — Źródła, portale i linki", () => {
  beforeEach(() => vi.clearAllMocks());

  it("Rada nadzorcza nie dostaje lejka źródeł, tylko notkę", () => {
    renderAs("board");
    expect(screen.getByText("integracje")).toBeInTheDocument();
    expect(screen.getByText("linki")).toBeInTheDocument();
    expect(screen.queryByText("lejek źródeł")).not.toBeInTheDocument();
    expect(screen.getByText(/Źródła kandydatów nie są dostępne dla tej roli/)).toBeInTheDocument();
  });

  it("rekruter widzi lejek źródeł", () => {
    renderAs("recruiter");
    expect(screen.getByText("lejek źródeł")).toBeInTheDocument();
  });
});
