import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  CONTRACT_TERMINATION_REASONS: [{ value: "project_ended", label: "Koniec projektu" }],
}));

import {
  addDaysIso,
  buildClientReport,
  compareNullable,
  daysBetweenIso,
  endingByPerson,
  endingDecisionLine,
  endingNote,
  forecastAxis,
  forecastChange,
  forecastMonthLabel,
  marginFigureNote,
  nextSort,
  sortClientReport,
  sortPeopleReport,
  sortWindow,
  summarizeWindow,
  windowGapNote,
  windowMonthlyMargin,
  withoutRevenueNote,
  type MarginRow,
  type WindowContract,
} from "@/lib/contract-analytics";

const plain = (text: string | undefined | null) => text?.replace(/ /g, " ");

function contract(overrides: Partial<WindowContract> = {}): WindowContract {
  return {
    id: 1,
    candidate_id: 10,
    candidate_name: "Anna Przykładowa",
    client_id: 100,
    client_name: "Klient Testowy",
    start_date: "2026-11-23",
    end_date: "2026-12-31",
    rate_client: 150,
    rate_candidate: 110,
    margin: 40,
    currency: "PLN",
    rate_client_currency: "PLN",
    rate_candidate_currency: "PLN",
    rate_unit: "hourly",
    billing_hours_per_month: 168,
    termination_reason: null,
    prolongation_status: "unknown",
    ...overrides,
  };
}

function marginRow(overrides: Partial<MarginRow> = {}): MarginRow {
  return {
    client_id: 100,
    client_name: "Klient Testowy",
    active_contracts: 3,
    total_monthly_margin: 20000,
    total_monthly_revenue: 90000,
    margin_pct: 22.2,
    fx_missing: false,
    ...overrides,
  };
}

describe("liczby na górze", () => {
  it("procent marży idzie z serwera, po polsku, z kontraktami bez stawek", () => {
    expect(
      plain(
        marginFigureNote({
          margin_pct: 33.3,
          contracts_without_cost_leg: 1,
          contracts_without_revenue_leg: 2,
        }),
      ),
    ).toBe(
      "33,3 % z przychodu · 1 kontrakt bez stawki kosztowej poza marżą · Niepełne: 2 kontrakty bez stawki przychodowej poza sumą",
    );
  });

  it("bez procentu i bez braków podpis jest pusty", () => {
    expect(marginFigureNote({ margin_pct: null })).toBeUndefined();
    expect(marginFigureNote(undefined)).toBeUndefined();
    expect(withoutRevenueNote(0)).toBeUndefined();
    expect(withoutRevenueNote(5)).toBe("Niepełne: 5 kontraktów bez stawki przychodowej poza sumą");
  });
});

describe("okno 90 dni", () => {
  it("daty liczone bez strefy czasowej", () => {
    expect(addDaysIso("2026-11-20", 90)).toBe("2027-02-18");
    expect(addDaysIso("2026-12-31", 1)).toBe("2027-01-01");
    expect(daysBetweenIso("2026-11-20", "2026-11-30")).toBe(10);
    expect(daysBetweenIso("2026-11-20", "2026-11-18")).toBe(-2);
  });

  it("marża miesięczna jak `Contract.monthly_rate`: h × godziny, MD × 21, miesięczna bez zmian", () => {
    expect(windowMonthlyMargin(contract())).toBe(40 * 168);
    expect(windowMonthlyMargin(contract({ billing_hours_per_month: 160 }))).toBe(40 * 160);
    expect(windowMonthlyMargin(contract({ billing_hours_per_month: null }))).toBe(40 * 168);
    expect(windowMonthlyMargin(contract({ rate_unit: "daily", margin: 320 }))).toBe(320 * 21);
    expect(windowMonthlyMargin(contract({ rate_unit: "monthly", margin: 7000 }))).toBe(7000);
  });

  it("bez marży z serwera liczy różnicę stawek", () => {
    expect(windowMonthlyMargin(contract({ margin: undefined }))).toBe(40 * 168);
  });

  it("brak stawki, ukryte kwoty albo inna waluta → nie liczymy (nigdy zero)", () => {
    expect(windowMonthlyMargin(contract({ rate_client: null }))).toBeNull();
    expect(windowMonthlyMargin(contract({ rate_client_currency: "EUR" }))).toBeNull();
    expect(
      windowMonthlyMargin(
        contract({ rate_client_currency: null, rate_candidate_currency: null, currency: "EUR" }),
      ),
    ).toBeNull();
  });

  it("podsumowanie okna: osoby bez powtórzeń, suma tylko znanych PLN, braki osobno", () => {
    const summary = summarizeWindow([
      contract({ id: 1, candidate_id: 10 }),
      contract({ id: 2, candidate_id: 10, client_id: 101 }),
      contract({ id: 3, candidate_id: 11, rate_client: null }),
      contract({ id: 4, candidate_id: 12, rate_client_currency: "EUR", rate_candidate_currency: "EUR" }),
    ]);
    expect(summary).toEqual({
      contracts: 4,
      people: 3,
      margin: 2 * 40 * 168,
      withoutRates: 1,
      otherCurrency: 1,
    });
    expect(windowGapNote(summary)).toBe(
      "1 kontrakt bez stawek — ich marży nie liczymy · 1 kontrakt w innej walucie — poza sumą",
    );
    expect(windowGapNote(summarizeWindow([contract()]))).toBeNull();
  });

  it("puste okno: zero osób i zero marży", () => {
    expect(summarizeWindow([])).toEqual({ contracts: 0, people: 0, margin: 0, withoutRates: 0, otherCurrency: 0 });
  });

  it("drugi wiersz kończącej się umowy: powód, decyzja albo jej brak", () => {
    expect(endingNote(contract({ termination_reason: "project_ended" }))).toBe("koniec projektu");
    expect(endingNote(contract({ termination_reason: "inny_powod" }))).toBe("inny_powod");
    expect(endingNote(contract({ prolongation_status: "yes" }))).toBe("klient przedłuża");
    expect(endingNote(contract({ prolongation_status: "negotiate" }))).toBe("w negocjacjach");
    expect(endingNote(contract())).toBe("bez decyzji o przedłużeniu");
  });

  it("linia decyzji liczy koniec, brak decyzji i przedłużenia", () => {
    expect(
      endingDecisionLine([
        contract({ termination_reason: "project_ended" }),
        contract({ prolongation_status: "no" }),
        contract({ prolongation_status: "yes" }),
        contract(),
      ]),
    ).toBe("2 z decyzją o końcu · 1 bez decyzji o przedłużeniu · 1 klient przedłuża");
  });

  it("najbliższe najpierw, przy tej samej dacie większa marża wyżej, bez marży na końcu", () => {
    const sorted = sortWindow(
      [
        contract({ id: 1, end_date: "2026-12-31", margin: 10 }),
        contract({ id: 2, end_date: "2026-11-30", rate_client: null }),
        contract({ id: 3, end_date: "2026-11-30", margin: 50 }),
      ],
      "end_date",
    );
    expect(sorted.map((c) => c.id)).toEqual([3, 2, 1]);
  });
});

describe("tabela „kto ile przynosi”", () => {
  it("wiersz klienta niesie zmiany z okna; klient tylko ze startem dostaje własny wiersz", () => {
    const rows = buildClientReport(
      [marginRow()],
      [contract({ id: 1, client_id: 100 })],
      [contract({ id: 2, client_id: 200, client_name: "Nowy Klient" })],
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ clientId: 100, contracts: 3, margin: 20000 });
    expect(rows[0].ending.map((c) => c.id)).toEqual([1]);
    expect(rows[1]).toMatchObject({ clientId: 200, name: "Nowy Klient", contracts: null, margin: null });
    expect(rows[1].starting.map((c) => c.id)).toEqual([2]);
  });

  it("wiersz bez kursu FX nie pokazuje kwot (są częściowe)", () => {
    const [row] = buildClientReport([marginRow({ fx_missing: true, total_monthly_margin: 999 })], [], []);
    expect(row).toMatchObject({ fxMissing: true, revenue: null, margin: null, pct: null });
  });

  it("sortowanie: puste na końcu w obu kierunkach, remis po nazwie", () => {
    const rows = buildClientReport(
      [
        marginRow({ client_id: 1, client_name: "Beta", total_monthly_margin: 100 }),
        marginRow({ client_id: 2, client_name: "Alfa", total_monthly_margin: 100 }),
        marginRow({ client_id: 3, client_name: "Gamma", total_monthly_margin: 300 }),
      ],
      [],
      [contract({ client_id: 4, client_name: "Delta" })],
    );
    const desc = sortClientReport(rows, { key: "margin", dir: "desc" }).map((r) => r.name);
    expect(desc).toEqual(["Gamma", "Alfa", "Beta", "Delta"]);
    const asc = sortClientReport(rows, { key: "margin", dir: "asc" }).map((r) => r.name);
    expect(asc).toEqual(["Alfa", "Beta", "Gamma", "Delta"]);
    const byName = sortClientReport(rows, { key: "name", dir: "asc" }).map((r) => r.name);
    expect(byName).toEqual(["Alfa", "Beta", "Delta", "Gamma"]);
  });

  it("klik w nagłówek: ta sama kolumna odwraca, nowa — nazwa rosnąco, liczby malejąco", () => {
    expect(nextSort({ key: "margin", dir: "desc" }, "margin")).toEqual({ key: "margin", dir: "asc" });
    expect(nextSort({ key: "margin", dir: "desc" }, "name")).toEqual({ key: "name", dir: "asc" });
    expect(nextSort({ key: "name", dir: "asc" }, "revenue")).toEqual({ key: "revenue", dir: "desc" });
  });

  it("porównanie z pustymi i tekstem po polsku", () => {
    expect(compareNullable(null, 5, "asc")).toBe(1);
    expect(compareNullable(5, null, "desc")).toBe(-1);
    expect(compareNullable("Łódź", "Lublin", "asc")).toBeGreaterThan(0);
  });

  it("konsultanci: koniec umowy w oknie i sortowanie po nim", () => {
    const ending = [
      contract({ id: 1, candidate_id: 10, end_date: "2026-12-31" }),
      contract({ id: 2, candidate_id: 10, end_date: "2026-11-30" }),
      contract({ id: 3, candidate_id: 11, end_date: "2026-12-15" }),
    ];
    const map = endingByPerson(ending);
    expect(map.get(10)?.id).toBe(2);
    const people: MarginRow[] = [
      { candidate_id: 12, candidate_name: "Cezary Testowy", active_contracts: 1, total_monthly_margin: 1, total_monthly_revenue: 2, margin_pct: 50 },
      { candidate_id: 11, candidate_name: "Beata Testowa", active_contracts: 1, total_monthly_margin: 1, total_monthly_revenue: 2, margin_pct: 50 },
      { candidate_id: 10, candidate_name: "Adam Testowy", active_contracts: 1, total_monthly_margin: 1, total_monthly_revenue: 2, margin_pct: 50 },
    ];
    const sorted = sortPeopleReport(people, { key: "ending", dir: "asc" }, map);
    expect(sorted.map((r) => r.candidate_id)).toEqual([10, 11, 12]);
  });
});

describe("prognoza", () => {
  it("etykieta miesiąca po polsku, nie z locale backendu", () => {
    expect(forecastMonthLabel("2026-09", "Sep 2026")).toBe("wrz 2026");
    expect(forecastMonthLabel("zły", "Sep 2026")).toBe("Sep 2026");
  });

  it("oś przycięta do zakresu zmian: max na 30 %, min na 80 % wysokości", () => {
    const { hi, lo } = forecastAxis([3_283_652, 3_199_328]);
    const y = (v: number) => (hi - v) / (hi - lo);
    expect(y(3_283_652)).toBeCloseTo(0.3);
    expect(y(3_199_328)).toBeCloseTo(0.8);
  });

  it("płaska seria i pusta lista nie dzielą przez zero", () => {
    const flat = forecastAxis([1000, 1000]);
    expect(flat.hi).toBeGreaterThan(flat.lo);
    expect(forecastAxis([])).toEqual({ hi: 1, lo: 0 });
  });

  it("zmiana od pierwszego do ostatniego miesiąca; jeden miesiąc to brak zmiany", () => {
    const month = (m: string, margin: number) => ({ month: m, month_label: m, revenue: 0, margin, active_count: 1 });
    expect(forecastChange([month("2026-11", 1000), month("2027-10", 900)])).toEqual({ change: -100, pct: -10 });
    expect(forecastChange([month("2026-11", 0), month("2027-10", 900)])).toEqual({ change: 900, pct: null });
    expect(forecastChange([month("2026-11", 1000)])).toBeNull();
  });
});
