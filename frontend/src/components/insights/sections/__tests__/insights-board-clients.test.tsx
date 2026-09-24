/**
 * Sekcje `/api/insights/*` dla zakładek „Klienci & Delivery" i „Zarząd".
 *
 * Testy pilnują czterech reguł, których złamanie jest DEFEKTEM, nie kwestią
 * gustu — i każda z nich raz już wyszła na produkcji:
 *
 * 1. Awaria nie może renderować się jako pustka (403/500 ≠ „brak danych").
 * 2. `null` to „nie policzone", `0` to „policzone i wyszło zero" — na ekranie
 *    z pieniędzmi to jest różnica między pytaniem a werdyktem.
 * 3. Procentów nie przycinamy do 100 — 120% jest sygnałem, nie błędem widoku.
 * 4. Kafel będący sumą zgadza się z listą pod nim (jedna koperta, nie drugie
 *    zapytanie), a niepełna suma jest oznaczona.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { formatPLN } from "@/components/insights/sections/_shared";
import {
  barWidth,
  count,
  money,
  pct,
  signedPct,
} from "@/components/insights/sections/InsightsFormat";
import { InsightsClientsRanking } from "@/components/insights/sections/InsightsClientsRanking";
import type { InsightsPeriodParams } from "@/lib/insights-api";

const PERIOD: InsightsPeriodParams = { period: "month", offset: 0 };

const WINDOW = {
  kind: "month" as const,
  start: "2026-08-01T00:00:00+02:00",
  end: "2026-09-01T00:00:00+02:00",
  timezone: "Europe/Warsaw",
};

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

/** Odpowiedzi po DOKŁADNYM URL-u — prefiksy `/delivery-leads` się nakładają. */
function respond(map: Record<string, unknown>) {
  mocks.get.mockImplementation((url: string) => {
    if (!(url in map)) {
      return Promise.reject(new Error(`Nieoczekiwany URL w teście: ${url}`));
    }
    const value = map[url];
    if (value instanceof Error) return Promise.reject(value);
    return Promise.resolve({ data: value });
  });
}

function renderSection(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

/**
 * Wartość kafla `KpiCard` po jego etykiecie, w obrębie nazwanej grupy.
 *
 * `KpiCard` renderuje wartość BEZPOŚREDNIO przed etykietą, więc to jedyny
 * sposób powiązania liczby z jej podpisem bez dokładania `data-testid` do
 * współdzielonego kitu (`_shared.tsx` jest poza zakresem tej zmiany).
 * Zakres jest konieczny, bo „Placementy" i „Przychód / mc" występują na tym
 * ekranie dwa razy: raz jako wartość bieżąca, raz jako delta.
 */
function tileValue(groupLabel: string, label: string): string {
  const group = screen.getByRole("group", { name: groupLabel });
  const node = within(group).getByText(label);
  return node.previousElementSibling?.textContent?.trim() ?? "";
}

const FINANCE_COMPLETE = {
  asof: "2026-08-31",
  basis: "mrr_from_rate_schedules",
  revenue_monthly_pln: 250000,
  consultant_cost_monthly_pln: 180000,
  margin_monthly_pln: 70000,
  margin_pct: 28.0,
  active_consultants: 42,
  active_contracts: 45,
  priced_contracts: 44,
  contracts_without_cost_leg: 0,
  complete: true,
};

const DELTA_ZERO = {
  current: 0,
  previous: 0,
  delta: 0,
  change_pct: null as number | null,
};

function boardPayload(patch: Record<string, unknown> = {}) {
  return {
    period: WINDOW,
    kpis: {
      placements_definition: "first_hired_per_candidate_job",
      placements: 7,
      verified: 30,
      cv_sent: 18,
      interview: 11,
      funnel_efficiency_pct: 23.3,
      jobs_closed: 12,
      jobs_closed_with_placement: 5,
      hit_ratio_pct: 41.7,
      hit_ratio_definition: "closed_jobs_with_at_least_one_placement",
      finance: FINANCE_COMPLETE,
    },
    trend: {
      months: [
        {
          month: "2026-08",
          label: "sie 2026",
          asof: "2026-08-31",
          placements: 7,
          revenue_monthly_pln: 250000,
          consultant_cost_monthly_pln: 180000,
          margin_monthly_pln: 70000,
          consultants: 42,
          active_contracts: 45,
          complete: true,
        },
      ],
    },
    comparison: {
      previous_period: WINDOW,
      previous_asof: "2026-07-31",
      placements: { ...DELTA_ZERO, current: 7, previous: 5, change_pct: 40.0 },
      revenue_monthly_pln: DELTA_ZERO,
      margin_monthly_pln: DELTA_ZERO,
      active_consultants: DELTA_ZERO,
      complete: true,
    },
    degraded: null,
    ...patch,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("InsightsFormat — kontrakt `null` vs `0`", () => {
  it("kwota `null` to „—”, a zero to policzone zero", () => {
    expect(money(null)).toBe("—");
    expect(money(undefined)).toBe("—");
    expect(money(0)).toBe(formatPLN(0));
    expect(count(null)).toBe("—");
    expect(count(0)).toBe("0");
  });

  it("procentu nie przycina do 100 — przycięty jest wyłącznie pasek", () => {
    expect(pct(120.4)).toBe("120.4%");
    expect(pct(null)).toBe("—");
    expect(signedPct(null)).toBe("—");
    expect(signedPct(12.5)).toBe("+12.5%");
    // Geometria toru, nigdy liczba.
    expect(barWidth(120.4)).toBe(100);
    expect(barWidth(null)).toBe(0);
  });
});

describe("InsightsClientsRanking", () => {
  const rankingPayload = {
    period: WINDOW,
    valuation: {
      on: "2026-08-31",
      basis: "live_contracts",
      note: "Marża/MRR to bieżące kontrakty wycenione stawkami z harmonogramów.",
    },
    totals: {
      clients: 3,
      active_clients: 2,
      active_consultants: 9,
      active_contracts: 10,
      active_orders_count: 4,
      monthly_margin_complete: false,
      monthly_revenue_complete: true,
      revenue_complete: true,
      monthly_margin_total: 3000,
      total_revenue_all_time: 900000,
      active_revenue: 120000,
      monthly_revenue_total: 16000,
    },
    clients: [
      {
        client_id: 1,
        name: "Alfa",
        industry: "bankowość",
        head_dl_id: 5,
        head_dl_name: "Anna Nowak",
        total_revenue_all_time: 500000,
        active_revenue: 70000,
        monthly_margin_total: 2000,
        monthly_revenue_total: 10000,
        active_orders_count: 2,
        active_consultants: 5,
        active_contracts: 6,
        framework_status: "active",
        framework_expiry_date: "2027-01-31",
        revenue_complete: true,
        margin_complete: true,
        monthly_revenue_complete: true,
      },
      {
        client_id: 2,
        name: "Beta",
        industry: null,
        head_dl_id: null,
        head_dl_name: null,
        total_revenue_all_time: 400000,
        active_revenue: 50000,
        monthly_margin_total: 1000,
        monthly_revenue_total: 6000,
        active_orders_count: 2,
        active_consultants: 4,
        active_contracts: 4,
        framework_status: null,
        framework_expiry_date: null,
        revenue_complete: true,
        margin_complete: true,
        monthly_revenue_complete: true,
      },
      {
        client_id: 3,
        name: "Gamma",
        industry: null,
        head_dl_id: null,
        head_dl_name: null,
        total_revenue_all_time: 0,
        active_revenue: 0,
        monthly_margin_total: null,
        monthly_revenue_total: null,
        active_orders_count: 0,
        active_consultants: 0,
        active_contracts: 0,
        framework_status: null,
        framework_expiry_date: null,
        revenue_complete: true,
        margin_complete: false,
        monthly_revenue_complete: true,
      },
    ],
  };

  it("kafel marży równa się sumie kolumny pod nim", async () => {
    respond({ "/api/insights/clients/ranking": rankingPayload });

    renderSection(<InsightsClientsRanking period={PERIOD} />);

    expect(await screen.findByText("Alfa")).toBeInTheDocument();
    // Kafel jest foldem po tej samej liście, więc musi dać się sprawdzić
    // dodaniem widocznych wierszy: 2000 + 1000 + („—" = brak, nie zero).
    expect(tileValue("Kafle rankingu klientów", "Marża / mc")).toBe(
      formatPLN(3000),
    );

    const rows = screen.getAllByRole("row").slice(1); // bez nagłówka
    const marginCells = rows.map(
      (row) => within(row).getAllByRole("cell")[4].textContent ?? "",
    );
    expect(marginCells[0]).toContain(formatPLN(2000));
    expect(marginCells[1]).toContain(formatPLN(1000));
    // Wiersz bez policzalnej marży pokazuje „—", nie zero.
    expect(marginCells[2]).toContain("—");
  });

  it("kafel przychodu to suma przychodu z kontraktów, nie wartość zamówień (UAT M10-B01)", async () => {
    respond({ "/api/insights/clients/ranking": rankingPayload });

    renderSection(<InsightsClientsRanking period={PERIOD} />);

    expect(await screen.findByText("Alfa")).toBeInTheDocument();
    expect(
      tileValue("Kafle rankingu klientów", "Przychód / mc (dzisiejsze kontrakty)"),
    ).toBe(
      formatPLN(16000),
    );
    expect(screen.queryByText("Aktywne MRR / mc")).toBeNull();
    const rows = screen.getAllByRole("row").slice(1);
    const revenueCells = rows.map(
      (row) => within(row).getAllByRole("cell")[3].textContent ?? "",
    );
    expect(revenueCells[0]).toContain(formatPLN(10000));
    expect(revenueCells[1]).toContain(formatPLN(6000));
    expect(revenueCells[2]).toContain("—");
  });

  it("oznacza, że suma jest zaniżona, gdy marży nie dało się policzyć", async () => {
    respond({ "/api/insights/clients/ranking": rankingPayload });

    renderSection(<InsightsClientsRanking period={PERIOD} />);

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(/jest zaniżony, nie równy zeru/);
  });

  it("przy 403 nie renderuje pustej tabeli", async () => {
    respond({ "/api/insights/clients/ranking": httpError(403) });

    renderSection(<InsightsClientsRanking period={PERIOD} />);

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(
      screen.queryByText("Brak klientów z żywymi kontraktami."),
    ).not.toBeInTheDocument();
  });
});
