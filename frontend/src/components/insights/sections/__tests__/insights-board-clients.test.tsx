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
import { InsightsBoardKPI } from "@/components/insights/sections/InsightsBoardKPI";
import { InsightsClientsHitRatio } from "@/components/insights/sections/InsightsClientsHitRatio";
import { InsightsClientsRanking } from "@/components/insights/sections/InsightsClientsRanking";
import { InsightsDeliveryLeads } from "@/components/insights/sections/InsightsDeliveryLeads";
import { InsightsPlacementsByClient } from "@/components/insights/sections/InsightsPlacementsByClient";
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

describe("InsightsBoardKPI", () => {
  it("kwoty `null` renderuje jako „—”, nie jako zero", async () => {
    respond({
      "/api/insights/board": boardPayload({
        kpis: {
          ...boardPayload().kpis,
          hit_ratio_pct: null,
          finance: {
            ...FINANCE_COMPLETE,
            revenue_monthly_pln: null,
            margin_monthly_pln: null,
            margin_pct: null,
            complete: false,
          },
        },
      }),
    });

    renderSection(<InsightsBoardKPI period={PERIOD} />);

    expect(
      await screen.findByRole("group", { name: "Kafle finansowe" }),
    ).toBeInTheDocument();
    expect(tileValue("Kafle finansowe", "Przychód / mc")).toBe("—");
    expect(tileValue("Kafle finansowe", "Marża / mc")).toBe("—");
    // Zerowy mianownik hit ratio też jest luką, nie wynikiem 0%.
    expect(tileValue("Kafle rekrutacyjne", "Hit ratio")).toBe("—");
  });

  it("`degraded` degraduje kafle pieniędzy, a liczby zostają widoczne", async () => {
    respond({
      "/api/insights/board": boardPayload({
        degraded: {
          reasons: ["fx_missing"],
          fx: {
            currencies: ["EUR"],
            kpi_contracts_excluded_from_revenue: 2,
            kpi_contracts_excluded_from_margin: 2,
            months_affected: ["2026-07"],
          },
          contracts_without_cost_leg: 0,
          message: "Brak kursu NBP dla walut: EUR — kwoty są POMINIĘTE.",
        },
      }),
    });

    renderSection(<InsightsBoardKPI period={PERIOD} />);

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("Brak kursu NBP dla walut: EUR");
    expect(notice).toHaveTextContent("2026-07");
    // „Niepełne" to nie „nieznane" — schowanie kwot cofnęłoby nas do pustki
    // udającej dane, więc kafle muszą dalej pokazywać liczby.
    expect(tileValue("Kafle finansowe", "Przychód / mc")).toBe(
      formatPLN(250000),
    );
    expect(tileValue("Kafle rekrutacyjne", "Placementy")).toBe("7");
  });

  it("pisze na ekranie, co liczy jako placement i jako hit ratio", async () => {
    respond({ "/api/insights/board": boardPayload() });

    renderSection(<InsightsBoardKPI period={PERIOD} />);

    expect(
      await screen.findByText(/PIERWSZE „zatrudniony” dla pary/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/odsetek rekrutacji ZAMKNIĘTYCH w tym oknie/),
    ).toBeInTheDocument();
  });

  it("przy 500 mówi o awarii zamiast znikać z ekranu", async () => {
    respond({ "/api/insights/board": httpError(500) });

    const { container } = renderSection(<InsightsBoardKPI period={PERIOD} />);

    expect(
      await screen.findByText(
        /Nie udało się pobrać danych sekcji „Kokpit zarządu"/,
      ),
    ).toBeInTheDocument();
    expect(container).not.toBeEmptyDOMElement();
  });

  it("przy 403 tłumaczy uprawnienia i nie proponuje ponowienia", async () => {
    respond({ "/api/insights/board": httpError(403) });

    renderSection(<InsightsBoardKPI period={PERIOD} />);

    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.getByText(/Dane NIE są puste/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Spróbuj ponownie/ }),
    ).not.toBeInTheDocument();
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
      revenue_complete: true,
      monthly_margin_total: 3000,
      total_revenue_all_time: 900000,
      active_revenue: 120000,
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
        active_orders_count: 2,
        active_consultants: 5,
        active_contracts: 6,
        framework_status: "active",
        framework_expiry_date: "2027-01-31",
        revenue_complete: true,
        margin_complete: true,
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
        active_orders_count: 2,
        active_consultants: 4,
        active_contracts: 4,
        framework_status: null,
        framework_expiry_date: null,
        revenue_complete: true,
        margin_complete: true,
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
        active_orders_count: 0,
        active_consultants: 0,
        active_contracts: 0,
        framework_status: null,
        framework_expiry_date: null,
        revenue_complete: true,
        margin_complete: false,
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
      (row) => within(row).getAllByRole("cell")[5].textContent ?? "",
    );
    expect(marginCells[0]).toContain(formatPLN(2000));
    expect(marginCells[1]).toContain(formatPLN(1000));
    // Wiersz bez policzalnej marży pokazuje „—", nie zero.
    expect(marginCells[2]).toContain("—");
  });

  it("oznacza, że suma jest zaniżona, gdy marży nie dało się policzyć", async () => {
    respond({ "/api/insights/clients/ranking": rankingPayload });

    renderSection(<InsightsClientsRanking period={PERIOD} />);

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent(/Suma jest zaniżona, nie równa zeru/);
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

describe("InsightsClientsHitRatio", () => {
  function hitRatioPayload(patch: Record<string, unknown> = {}) {
    return {
      period: WINDOW,
      placement_definition: "first_hired_per_candidate_and_job",
      sort: "hit_ratio",
      min_closed: 3,
      excluded_reasons: [],
      clients: [
        {
          client_id: 1,
          client_name: "Alfa",
          client_status: "active",
          closed_jobs: 5,
          filled_jobs: 6,
          lost_jobs: 0,
          total_vacancies: 5,
          placements: 6,
          // Powyżej 100% — placementy domknęły zapytania spoza okna.
          hit_ratio: 120.0,
          fill_rate: 120.0,
          active_jobs: 1,
          target_achieved: true,
          close_reasons: {},
        },
      ],
      overall: {
        total_clients: 1,
        clients_with_closed_jobs: 1,
        total_closed_jobs: 5,
        total_filled_jobs: 6,
        total_lost_jobs: 0,
        total_vacancies: 5,
        total_placements: 6,
        global_hit_ratio: 120.0,
        global_fill_rate: 120.0,
        avg_hit_ratio: 120.0,
        avg_fill_rate: 120.0,
        target_count: 1,
        hit_ratio_target_pct: 30.0,
      },
      at_risk: {
        previous_period: WINDOW,
        drop_threshold_pp: 20.0,
        min_closed: 3,
        clients: [],
        not_comparable: 4,
      },
      ...patch,
    };
  }

  it("nie przycina hit ratio do 100%", async () => {
    respond({ "/api/insights/clients/hit-ratio": hitRatioPayload() });

    renderSection(<InsightsClientsHitRatio period={PERIOD} />);

    expect(await screen.findByText("Alfa")).toBeInTheDocument();
    expect(screen.getAllByText("120.0%").length).toBeGreaterThan(0);
    expect(screen.queryByText("100.0%")).not.toBeInTheDocument();
  });

  it("pusta lista at-risk mówi, ilu klientów nie dało się porównać", async () => {
    respond({ "/api/insights/clients/hit-ratio": hitRatioPayload() });

    renderSection(<InsightsClientsHitRatio period={PERIOD} />);

    expect(
      await screen.findByText(/nie ma z czym porównywać/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/To NIE jest zerowa skuteczność/),
    ).toBeInTheDocument();
  });

  it("przy 500 nie mówi „brak klientów”", async () => {
    respond({ "/api/insights/clients/hit-ratio": httpError(500) });

    renderSection(<InsightsClientsHitRatio period={PERIOD} />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Żaden klient nie ma w tym oknie/)).toBeNull();
  });
});

describe("InsightsDeliveryLeads", () => {
  const dlPayload = {
    period: WINDOW,
    recruitment_type: "body_leasing",
    hit_ratio_target_pct: 30.0,
    open_pipeline_scope: "snapshot_now",
    hit_ratio_is_cross_cohort: true,
    per_dl: [
      {
        user_id: 7,
        name: "Anna Nowak",
        is_active: true,
        total_requests: 0,
        total_vacancies: 0,
        placements: 2,
        // Zero zapytań w oknie → wskaźnika NIE DA SIĘ policzyć.
        hit_ratio: null,
        fill_rate: null,
        avg_vacancies_per_request: null,
        open_requests: 3,
        open_vacancies: 4,
        target_achieved: null,
        clients: ["Alfa"],
      },
    ],
    overall: {
      dl_count: 1,
      total_requests: 0,
      total_vacancies: 0,
      total_placements: 2,
      total_open_requests: 3,
      total_open_vacancies: 4,
      hit_ratio: null,
      fill_rate: null,
      avg_hit_ratio: null,
      dl_with_hit_ratio: 0,
      not_assessable_count: 1,
      target_count: 0,
    },
    unattributed: {
      requests: 6,
      vacancies: 8,
      placements: 3,
      open_requests: 1,
    },
  };

  it("DL bez mianownika ma „—”, a nie „poniżej progu”", async () => {
    respond({ "/api/insights/delivery-leads": dlPayload });

    renderSection(<InsightsDeliveryLeads period={PERIOD} />);

    const nameCell = await screen.findByRole("button", { name: /Anna Nowak/ });
    const cells = within(nameCell.closest("tr") as HTMLElement).getAllByRole(
      "cell",
    );
    expect(cells[4]).toHaveTextContent("—"); // hit ratio
    expect(cells[7]).toHaveTextContent("—"); // cel
    expect(screen.queryByText(/poniżej 30%/)).not.toBeInTheDocument();
  });

  it("pokazuje placementy bez przypisanego DL obok rankingu", async () => {
    respond({ "/api/insights/delivery-leads": dlPayload });

    renderSection(<InsightsDeliveryLeads period={PERIOD} />);

    expect(
      await screen.findByText(/Bez przypisanego Delivery Leada/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/nie wchodzą do żadnego wiersza wyżej/),
    ).toBeInTheDocument();
  });

  it("przy 500 nie udaje pustego rankingu", async () => {
    respond({ "/api/insights/delivery-leads": httpError(500) });

    renderSection(<InsightsDeliveryLeads period={PERIOD} />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak Delivery Leadów z aktywnością w tym oknie."),
    ).not.toBeInTheDocument();
  });
});

describe("InsightsPlacementsByClient", () => {
  it("przy 500 nie mówi „brak placementów”", async () => {
    respond({
      "/api/insights/delivery-leads/placements-by-client": httpError(500),
    });

    renderSection(<InsightsPlacementsByClient period={PERIOD} />);

    expect(
      await screen.findByText(/Nie udało się pobrać danych sekcji/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Brak placementów w wybranym oknie."),
    ).not.toBeInTheDocument();
  });

  it("klienta bez nazwy renderuje jawnie, a udziały bierze z koperty", async () => {
    respond({
      "/api/insights/delivery-leads/placements-by-client": {
        period: WINDOW,
        recruitment_type: "body_leasing",
        total_placements: 4,
        clients: [
          {
            client_id: 1,
            client_name: "Alfa",
            placements: 3,
            share_pct: 75.0,
          },
          {
            client_id: null,
            client_name: "(bez klienta)",
            placements: 1,
            share_pct: 25.0,
          },
        ],
      },
    });

    renderSection(<InsightsPlacementsByClient period={PERIOD} />);

    expect(await screen.findByText("(bez klienta)")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
  });
});
