/**
 * /contracts/analytics: nieudane pobranie marży NIE może wyglądać jak zero.
 *
 * To ekran, na którym admin odpowiada sobie na pytanie „ile zarabiamy w tym
 * miesiącu". Do sierpnia 2026 żadne z siedmiu zapytań nie czytało `isError`,
 * a `(byClient ?? []).reduce(...)` zwijał 500/403/timeout w pewne siebie
 * „0,00 zł" na kaflach „Miesięczna marża" i „Miesięczny przychód". Nic na
 * ekranie nie było czerwone i nic nie proponowało ponowienia.
 *
 * Test odrzuca obietnicę `api.get` dla margin-by-client — czyli idzie dokładnie
 * tą ścieżką, na której siedział defekt.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn(), expansion: vi.fn() }));

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

vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => mocks.get(...a) },
  contractAnalyticsExpansionApi: {
    roleClientMix: () => mocks.expansion("roleClientMix"),
    locationDistribution: () => mocks.expansion("locationDistribution"),
    terminationAnalysis: () => mocks.expansion("terminationAnalysis"),
  },
  CONTRACT_TERMINATION_REASONS: [],
}));

// Bramka rolowa strony nie jest przedmiotem tego testu.
vi.mock("@/components/RequireRole", () => ({
  RequireRole: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

import ContractAnalyticsPage from "@/app/contracts/analytics/page";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ContractAnalyticsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.expansion.mockReset();
  mocks.expansion.mockRejectedValue(httpError(500));
});

describe("ContractAnalyticsPage — kafle pieniężne", () => {
  it("gdy margin-totals pada, marża i przychód pokazują „—”, nie 0,00 zł", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url.includes("margin-totals")) {
        return Promise.reject(httpError(500));
      }
      if (url.includes("margin-by-client")) {
        return Promise.reject(httpError(500));
      }
      if (url.includes("margin-by-contractor"))
        return Promise.resolve({ data: [] });
      if (url.includes("utilization")) return Promise.reject(httpError(500));
      return Promise.resolve({ data: { horizon_months: 12, months: [] } });
    });

    renderPage();

    expect(
      await screen.findByText("Nie udało się pobrać marży"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Nie udało się pobrać przychodu"),
    ).toBeInTheDocument();
    // Regresja byłaby CICHA: sformatowane zero jest nieodróżnialne od wyniku.
    expect(screen.queryByText(/0,00/)).not.toBeInTheDocument();
  });

  it("kafle biorą sumy z margin-totals, nie z przyciętego rankingu", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url.includes("margin-totals")) {
        // Sumy firmowe są WIĘKSZE niż to, co widać w rankingu obok: ranking
        // jest przycięty do 20 klientów po marży, więc klient o wysokim
        // przychodzie i niskiej marży z niego wypada (audyt 18.09.2026 —
        // z kafla przychodu znikało 217 060 zł).
        return Promise.resolve({
          data: {
            clients: 30,
            active_contracts: 40,
            total_monthly_margin: 1000,
            total_monthly_revenue: 5000,
            margin_pct: 20,
            fx_missing: false,
          },
        });
      }
      if (url.includes("margin-by-client")) {
        return Promise.resolve({
          data: [
            {
              client_id: 1,
              client_name: "BIK",
              active_contracts: 2,
              total_monthly_margin: 111,
              total_monthly_revenue: 222,
              margin_pct: 50,
            },
          ],
        });
      }
      if (url.includes("margin-by-contractor"))
        return Promise.resolve({ data: [] });
      if (url.includes("utilization")) {
        return Promise.resolve({
          data: {
            total_candidates: 10,
            candidates_active: 4,
            active_contracts: 6,
            candidates_on_bench: 6,
            utilization_pct: 40,
            avg_bench_days: 12,
          },
        });
      }
      return Promise.resolve({ data: { horizon_months: 12, months: [] } });
    });

    renderPage();

    expect(await screen.findByText("20.0% z przychodu")).toBeInTheDocument();
    expect(
      screen.queryByText("Nie udało się pobrać marży"),
    ).not.toBeInTheDocument();
    // Regresja byłaby cicha: suma policzona z listy dałaby 111 / 222 zł.
    expect(
      screen.getByText("Miesięczna marża").parentElement,
    ).toHaveTextContent(/1[\s ]?000,00/);
  });
});

describe("ContractAnalyticsPage — degradacja kursów FX", () => {
  it("oznacza zdegradowane wiersze i nie sumuje ich jak kompletnych kwot", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url.includes("margin-totals")) {
        return Promise.resolve({
          data: {
            clients: 2,
            active_contracts: 2,
            total_monthly_margin: 1099,
            total_monthly_revenue: 5499,
            margin_pct: 20,
            fx_missing: true,
          },
        });
      }
      if (url.includes("margin-by-client")) {
        return Promise.resolve({
          data: [
            {
              client_id: 1,
              client_name: "Klient kompletny",
              active_contracts: 1,
              total_monthly_margin: 100,
              total_monthly_revenue: 500,
              margin_pct: 20,
              fx_missing: false,
            },
            {
              client_id: 2,
              client_name: "Klient bez kursu",
              active_contracts: 1,
              // Backend zwraca sumę dostępnych nóg, ale nie jest to pełna
              // kwota. UI ma ją ukryć, a nie dodać do kafli sumarycznych.
              total_monthly_margin: 999,
              total_monthly_revenue: 4999,
              margin_pct: 20,
              fx_missing: true,
            },
          ],
        });
      }
      if (url.includes("margin-by-contractor")) {
        return Promise.resolve({ data: [] });
      }
      if (url.includes("utilization")) {
        return Promise.resolve({
          data: {
            total_candidates: 2,
            candidates_active: 2,
            active_contracts: 2,
            candidates_on_bench: 0,
            utilization_pct: 100,
            avg_bench_days: null,
          },
        });
      }
      return Promise.resolve({ data: { horizon_months: 12, months: [] } });
    });

    renderPage();

    expect(
      await screen.findByText(/Dane finansowe są niepełne/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Miesięczna marża").parentElement,
    ).toHaveTextContent("—Niepełne dane — brak kursu FX");
    expect(
      screen.getByText("Miesięczny przychód").parentElement,
    ).toHaveTextContent("—Niepełne dane — brak kursu FX");

    const degradedRow = screen
      .getByRole("link", { name: "Klient bez kursu" })
      .closest("tr");
    expect(degradedRow).not.toBeNull();
    expect(degradedRow).toHaveTextContent("Brak kursu FX");
    expect(
      within(degradedRow as HTMLTableRowElement)
        .getAllByRole("cell")
        .slice(-3)
        .map((cell) => cell.textContent),
    ).toEqual(["—", "—", "—"]);
    expect(degradedRow).not.toHaveTextContent("4999");
  });

  it("fx_warnings z backendu jest widoczne nad wykresem prognozy", async () => {
    const warning =
      "Brak kursu NBP dla walut: EUR — kwoty w tych walutach POMINIĘTE w prognozie";
    mocks.get.mockImplementation((url: string) => {
      if (url.includes("revenue-forecast")) {
        return Promise.resolve({
          data: {
            horizon_months: 12,
            months: [
              {
                month: "2026-09",
                month_label: "Sep 2026",
                revenue: 100,
                margin: 10,
                active_count: 1,
              },
            ],
            fx_missing: true,
            fx_warnings: [warning],
          },
        });
      }
      return Promise.resolve({ data: [] });
    });

    renderPage();

    // Bez tego prognoza, która wyrzuciła wszystkie kontrakty w EUR/USD,
    // renderowała się jakby była kompletna.
    expect(await screen.findByText(warning)).toBeInTheDocument();
    // UAT M08-B06: etykiety po polsku, nie „Sep 2026” i „cnt” z backendu.
    expect(screen.getByText("wrz 2026")).toBeInTheDocument();
    expect(screen.getByText("1 kontrakt")).toBeInTheDocument();
    expect(screen.queryByText("Sep 2026")).toBeNull();
    expect(screen.queryByText(/\bcnt\b/)).toBeNull();
  });
});

describe("ContractAnalyticsPage — macierz rola × klient", () => {
  it("Σ używa unikalnych osób per rola zamiast sumy komórek klientów", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url.includes("margin-totals")) {
        return Promise.resolve({
          data: {
            clients: 0,
            active_contracts: 0,
            total_monthly_margin: 0,
            total_monthly_revenue: 0,
            margin_pct: null,
            fx_missing: false,
          },
        });
      }
      if (url.includes("margin-by")) return Promise.resolve({ data: [] });
      if (url.includes("utilization")) {
        return Promise.resolve({
          data: {
            total_candidates: 1,
            candidates_active: 1,
            active_contracts: 2,
            candidates_on_bench: 0,
            utilization_pct: 100,
            avg_bench_days: null,
          },
        });
      }
      return Promise.resolve({ data: { horizon_months: 12, months: [] } });
    });
    mocks.expansion.mockImplementation((name: string) => {
      if (name === "roleClientMix") {
        return Promise.resolve({
          data: {
            total_active: 1,
            total_active_contracts: 2,
            role_totals: { Developer: 1 },
            rows: [
              {
                role: "Developer",
                client_id: 1,
                client_name: "Client A",
                active_count: 1,
                pct_of_total: 100,
              },
              {
                role: "Developer",
                client_id: 2,
                client_name: "Client B",
                active_count: 1,
                pct_of_total: 100,
              },
            ],
            roles: ["Developer"],
            clients: [
              { id: 1, name: "Client A" },
              { id: 2, name: "Client B" },
            ],
          },
        });
      }
      return Promise.reject(httpError(500));
    });

    renderPage();

    expect(
      await screen.findByText(/1 kontraktor \/ 2 kontraktów/i),
    ).toBeInTheDocument();
    const row = screen.getByText("Developer").closest("tr");
    expect(row).not.toBeNull();
    expect(
      within(row as HTMLTableRowElement)
        .getAllByRole("cell")
        .map((cell) => cell.textContent),
    ).toEqual(["Developer", "1", "1", "1"]);
  });
});
