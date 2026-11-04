/**
 * „Mój czas → Premie i stawka” na przełomie roku (audyt A2, 19.10.2026):
 * 1.01 „premie wypłacone” nie spadają do zera, a „Moje rozliczenie” pokazuje
 * grudzień — w styczniu zakładka pyta też o poprzedni rok. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn() } }));
vi.mock("@/lib/api/hr", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/hr")>("@/lib/api/hr");
  return {
    ...actual,
    useMyHrProfile: () => ({ data: { has_profile: true, employment_type: "b2b" } }),
  };
});

import type { MyPayroll, MySettlement, SettlementMonth } from "@/lib/api/hr-payroll";

import { MyBonusesTab, myStats } from "../MyBonusesTab";

const payroll: MyPayroll = { current_rate: null, rates: [], bonuses: [], forecast: [] };

function settlementMonth(year: number, month: number): SettlementMonth {
  return {
    year,
    month,
    label: month === 12 ? `grudzień ${year}` : `miesiąc ${month} ${year}`,
    final: true,
    hours: "160.00",
    hours_source: "frozen",
    timesheet_status: "approved",
    rate_missing: false,
    lines: [
      { currency: "PLN", hourly_rate: "90.00", hours_amount: "14400.00", bonus_total: "500.00", total: "14900.00" },
    ],
  };
}

const nbsp = (value: string) => value.replace(/\s/g, " ");

afterEach(() => {
  mocks.get.mockReset();
  vi.useRealTimers();
});

describe("premie wypłacone na przełomie roku", () => {
  const lastYear: MySettlement = { year: 2026, months: [], bonuses_paid: { PLN: "1500.00" } };

  it("w styczniu liczba z poprzedniego roku, z rokiem w etykiecie", () => {
    const stat = myStats(payroll, "2027-01-05", lastYear).find((s) => s.id === "paid");
    expect(stat?.label).toBe("premie wypłacone w 2026");
    expect(nbsp(String(stat?.value))).toBe("1500,00 zł");
  });

  it("od lutego poprzedni rok już się nie liczy", () => {
    expect(myStats(payroll, "2027-02-05", lastYear).some((s) => s.id === "paid")).toBe(false);
  });

  it("5 stycznia zakładka pyta o 2026 i pokazuje grudzień w „Moim rozliczeniu”", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2027-01-05T10:00:00+01:00"));
    mocks.get.mockImplementation(async (url: string, config?: { params?: { year?: number } }) => {
      if (url === "/api/hr/payroll/me") return { data: payroll };
      const year = config?.params?.year;
      return {
        data:
          year === 2026
            ? { year: 2026, months: [settlementMonth(2026, 12)], bonuses_paid: { PLN: "1500.00" } }
            : { year: 2027, months: [], bonuses_paid: {} },
      };
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MyBonusesTab />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Grudzień 2026")).toBeInTheDocument();
    // Osoba na B2B: „wynagrodzenie dodatkowe”, nie „premie” (21.10.2026).
    expect(screen.getByText("wynagrodzenie dodatkowe wypłacone w 2026")).toBeInTheDocument();
    expect(screen.queryByText(/nie ma jeszcze miesięcy/)).toBeNull();
    const years = mocks.get.mock.calls
      .filter(([url]) => url === "/api/hr/payroll/me/settlement")
      .map(([, config]) => config.params.year);
    expect(years).toEqual(expect.arrayContaining([2027, 2026]));
  });
});
