/**
 * Tabela „Klienci” (audyt 08.11.2026, B3): zamknięcia „do przejrzenia” stoją
 * osobno i nie obniżają hit ratio, a brak zatrudnień to „—”, nie zero.
 */
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import type {
  InsightsClientFunnelResponse,
  InsightsClientFunnelRow,
} from "@/lib/insights-api";

const mocks = vi.hoisted(() => ({ funnel: vi.fn() }));

vi.mock("@/lib/insights-api", async (orig) => ({
  ...(await orig<typeof import("@/lib/insights-api")>()),
  insightsBoardApi: { clientsFunnel: () => mocks.funnel() },
}));

import {
  funnelLede,
  InsightsClientFunnel,
} from "@/components/insights/sections/InsightsClientFunnel";

function row(partial: Partial<InsightsClientFunnelRow>): InsightsClientFunnelRow {
  return {
    client_id: 1,
    client_name: "Klient A",
    cv_sent: 0,
    client_interviews: 0,
    hires: 0,
    cv_per_hire: null,
    won: 0,
    lost: 0,
    unreviewed: 0,
    hit_ratio: null,
    first_cv_median_days: null,
    first_cv_jobs: 0,
    ...partial,
  };
}

function response(clients: InsightsClientFunnelRow[]): InsightsClientFunnelResponse {
  return {
    period: {},
    hit_ratio_since: "2026-10-11T22:00:00+00:00",
    hit_ratio_target_pct: 30,
    clients,
    totals: {
      clients: clients.length,
      cv_sent: clients.reduce((s, c) => s + c.cv_sent, 0),
      client_interviews: clients.reduce((s, c) => s + c.client_interviews, 0),
      hires: clients.reduce((s, c) => s + c.hires, 0),
      cv_per_hire: null,
      won: clients.reduce((s, c) => s + c.won, 0),
      lost: clients.reduce((s, c) => s + c.lost, 0),
      unreviewed: clients.reduce((s, c) => s + c.unreviewed, 0),
      hit_ratio: 40,
    },
  };
}

function renderTable() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <InsightsClientFunnel period={{ period: "quarter", offset: 0 }} />
    </QueryClientProvider>,
  );
}

describe("InsightsClientFunnel", () => {
  it("pokazuje liczby, hit ratio z ułamkiem i „do przejrzenia” osobno", async () => {
    mocks.funnel.mockResolvedValue(
      response([
        row({
          client_name: "Klient A",
          cv_sent: 811,
          client_interviews: 99,
          hires: 23,
          cv_per_hire: 35.3,
          won: 4,
          lost: 30,
          unreviewed: 10,
          hit_ratio: 11.8,
          first_cv_median_days: 1.2,
          first_cv_jobs: 12,
        }),
      ]),
    );

    renderTable();

    const cell = await screen.findByText("Klient A");
    const tr = cell.closest("tr") as HTMLElement;
    expect(within(tr).getByText("811")).toBeInTheDocument();
    expect(within(tr).getByText("35,3")).toBeInTheDocument();
    expect(within(tr).getByText("(4/34)")).toBeInTheDocument();
    expect(within(tr).getByText("10")).toBeInTheDocument();
    expect(within(tr).getByText("1,2 d")).toBeInTheDocument();
    expect(screen.getByText(/od 12\.10\.2026/)).toBeInTheDocument();
  });

  it("klient bez zatrudnień ma „—”, a nie zero w CV na zatrudnienie", async () => {
    mocks.funnel.mockResolvedValue(response([row({ client_name: "Bez", cv_sent: 5 })]));

    renderTable();

    const tr = (await screen.findByText("Bez")).closest("tr") as HTMLElement;
    expect(within(tr).getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("pusty okres ma własny napis, a nie pustą tabelę", async () => {
    mocks.funnel.mockResolvedValue(response([]));

    renderTable();

    expect(await screen.findByText(/nie ma CV, rozmów ani zamknięć/)).toBeInTheDocument();
    expect(screen.queryByTestId("client-funnel-table")).toBeNull();
  });

  it("awaria zapytania nie wygląda jak pusty okres", async () => {
    mocks.funnel.mockRejectedValue(new Error("500"));

    renderTable();

    expect(await screen.findByRole("button", { name: /spróbuj|ponów|odśwież/i })).toBeInTheDocument();
    expect(screen.queryByText(/nie ma CV, rozmów ani zamknięć/)).toBeNull();
  });

  it("zdanie nad tabelą porównuje udział w CV i w zatrudnieniach", () => {
    const data = response([
      row({ client_name: "Klient A", cv_sent: 62, hires: 35 }),
      row({ client_id: 2, client_name: "Klient B", cv_sent: 38, hires: 65 }),
    ]);
    expect(funnelLede(data)).toBe("Klient A dostaje 62% naszych CV i daje 35% zatrudnień.");
    expect(funnelLede(response([row({ cv_sent: 3, hires: 1 })]))).toBeNull();
  });
});
