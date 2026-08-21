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
import { render, screen } from "@testing-library/react";
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
  it("gdy margin-by-client pada, marża i przychód pokazują „—”, nie 0,00 zł", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url.includes("margin-by-client")) {
        return Promise.reject(httpError(500));
      }
      if (url.includes("margin-by-contractor")) return Promise.resolve({ data: [] });
      if (url.includes("utilization")) return Promise.reject(httpError(500));
      return Promise.resolve({ data: { horizon_months: 12, months: [] } });
    });

    renderPage();

    expect(
      await screen.findByText("Nie udało się pobrać marży"),
    ).toBeInTheDocument();
    expect(screen.getByText("Nie udało się pobrać przychodu")).toBeInTheDocument();
    // Regresja byłaby CICHA: sformatowane zero jest nieodróżnialne od wyniku.
    expect(screen.queryByText(/0,00/)).not.toBeInTheDocument();
  });

  it("gdy margin-by-client zwraca dane, kafle liczą sumy", async () => {
    mocks.get.mockImplementation((url: string) => {
      if (url.includes("margin-by-client")) {
        return Promise.resolve({
          data: [
            {
              client_id: 1,
              client_name: "BIK",
              active_contracts: 2,
              total_monthly_margin: 1000,
              total_monthly_revenue: 5000,
              margin_pct: 20,
            },
          ],
        });
      }
      if (url.includes("margin-by-contractor")) return Promise.resolve({ data: [] });
      if (url.includes("utilization")) {
        return Promise.resolve({
          data: {
            total_candidates: 10,
            candidates_active: 4,
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
    expect(screen.queryByText("Nie udało się pobrać marży")).not.toBeInTheDocument();
  });
});

describe("ContractAnalyticsPage — degradacja kursów FX", () => {
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
  });
});
