import { describe, expect, it } from "vitest";

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
  windowMarginGap,
  windowMonthlyMargin,
  withoutRevenueNote,
  type ClientSortKey,
  type MarginRow,
  type PersonSortKey,
  type WindowContract,
} from "@/lib/contract-analytics";

function wc(overrides: Partial<WindowContract> = {}): WindowContract {
  return {
    id: 1,
    candidate_id: 10,
    candidate_name: "Jan Testowy",
    client_id: 100,
    client_name: "Firma Testowa",
    start_date: "2026-01-01",
    end_date: "2026-12-31",
    rate_client: 150,
    rate_candidate: 100,
    ...overrides,
  };
}

function mr(overrides: Partial<MarginRow> = {}): MarginRow {
  return {
    active_contracts: 1,
    total_monthly_margin: 1000,
    total_monthly_revenue: 5000,
    margin_pct: 20,
    ...overrides,
  };
}

describe("podpisy liczb", () => {
  it("withoutRevenueNote: brak, zero, ujemne → undefined", () => {
    expect(withoutRevenueNote(undefined)).toBeUndefined();
    expect(withoutRevenueNote(0)).toBeUndefined();
    expect(withoutRevenueNote(-1)).toBeUndefined();
    expect(withoutRevenueNote(5)).toBe("Niepełne: 5 kontraktów bez stawki przychodowej poza sumą");
  });
  it("marginFigureNote: brak danych, brak procentu i braków → undefined", () => {
    expect(marginFigureNote(undefined)).toBeUndefined();
    expect(marginFigureNote({ margin_pct: null })).toBeUndefined();
  });
  it("marginFigureNote: kontrakty bez stawki kosztowej i przychodowej", () => {
    expect(
      marginFigureNote({ margin_pct: null, contracts_without_cost_leg: 2, contracts_without_revenue_leg: 1 }),
    ).toBe(
      "2 kontrakty bez stawki kosztowej poza marżą · Niepełne: 1 kontrakt bez stawki przychodowej poza sumą",
    );
  });
});

describe("daty okna", () => {
  it("dodawanie dni przez granicę roku i ujemne przesunięcie", () => {
    expect(addDaysIso("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDaysIso("2027-01-01T12:00:00", -1)).toBe("2026-12-31");
    expect(addDaysIso("2026-10-03", 90)).toBe("2027-01-01");
  });
  it("dni między datami: ujemne, gdy minęło", () => {
    expect(daysBetweenIso("2026-12-31", "2027-01-01")).toBe(1);
    expect(daysBetweenIso("2027-01-01", "2026-12-31")).toBe(-1);
  });
});

describe("marża w oknie — waluty i jednostki", () => {
  it("brak którejś stawki = no_rates", () => {
    expect(windowMarginGap(wc({ rate_client: null }))).toBe("no_rates");
    expect(windowMarginGap(wc({ rate_candidate: null }))).toBe("no_rates");
    expect(windowMonthlyMargin(wc({ rate_client: null }))).toBeNull();
  });
  it("waluta nogi wygrywa z walutą kontraktu; mała litera normalizowana", () => {
    expect(windowMarginGap(wc({ currency: "EUR" }))).toBe("other_currency");
    expect(windowMarginGap(wc({ currency: "EUR", rate_client_currency: "pln", rate_candidate_currency: "PLN" }))).toBeNull();
    expect(windowMarginGap(wc({ rate_candidate_currency: "eur" }))).toBe("other_currency");
    expect(windowMonthlyMargin(wc({ rate_client_currency: "EUR" }))).toBeNull();
  });
  it("godzina × 168 domyślnie, własne godziny, MD × 21, miesiąc × 1", () => {
    expect(windowMonthlyMargin(wc())).toBe(50 * 168);
    expect(windowMonthlyMargin(wc({ billing_hours_per_month: 160 }))).toBe(8000);
    expect(windowMonthlyMargin(wc({ billing_hours_per_month: 0 }))).toBe(50 * 168);
    expect(windowMonthlyMargin(wc({ rate_unit: "daily", rate_client: 1200, rate_candidate: 1000 }))).toBe(4200);
    expect(windowMonthlyMargin(wc({ rate_unit: "monthly", rate_client: 20000, rate_candidate: 15000 }))).toBe(5000);
  });
  it("marża z serwera wygrywa; ujemna marża zostaje ujemna; zero to zero", () => {
    expect(windowMonthlyMargin(wc({ margin: 10, rate_unit: "monthly" }))).toBe(10);
    expect(windowMonthlyMargin(wc({ rate_client: 90, rate_candidate: 100, rate_unit: "monthly" }))).toBe(-10);
    expect(windowMonthlyMargin(wc({ margin: 0 }))).toBe(0);
  });
});

describe("summarizeWindow / windowGapNote", () => {
  it("pusta lista", () => {
    const s = summarizeWindow([]);
    expect(s).toEqual({ contracts: 0, people: 0, margin: 0, withoutRates: 0, otherCurrency: 0 });
    expect(windowGapNote(s)).toBeNull();
  });
  it("osoba bez id liczona po kontrakcie; braki i inna waluta poza sumą", () => {
    const s = summarizeWindow([
      wc({ id: 1, rate_unit: "monthly" }),
      wc({ id: 2, candidate_id: null, rate_client: null }),
      wc({ id: 3, candidate_id: null, currency: "EUR" }),
      wc({ id: 4, rate_unit: "monthly" }),
    ]);
    expect(s).toEqual({ contracts: 4, people: 3, margin: 100, withoutRates: 1, otherCurrency: 1 });
    expect(windowGapNote(s)).toBe(
      "1 kontrakt bez stawek — ich marży nie liczymy · 1 kontrakt w innej walucie — poza sumą",
    );
    expect(windowGapNote({ ...s, withoutRates: 0, otherCurrency: 3 })).toBe("3 kontrakty w innej walucie — poza sumą");
  });
});

describe("endingNote / endingDecisionLine", () => {
  it("powód z listy, spoza listy i decyzje o przedłużeniu", () => {
    expect(endingNote(wc({ termination_reason: "project_ended" }))).toBe("koniec projektu");
    expect(endingNote(wc({ termination_reason: "Inny Powód" }))).toBe("inny powód");
    expect(endingNote(wc({ prolongation_status: "yes" }))).toBe("klient przedłuża");
    expect(endingNote(wc({ prolongation_status: "no" }))).toBe("klient nie przedłuża");
    expect(endingNote(wc({ prolongation_status: "negotiate" }))).toBe("w negocjacjach");
    expect(endingNote(wc())).toBe("bez decyzji o przedłużeniu");
  });
  it("pusta lista daje pusty napis; same przedłużenia", () => {
    expect(endingDecisionLine([])).toBe("");
    expect(endingDecisionLine([wc({ prolongation_status: "yes" })])).toBe("1 klient przedłuża");
    expect(
      endingDecisionLine([
        wc({ termination_reason: "other", prolongation_status: "yes" }),
        wc({ prolongation_status: "no" }),
        wc({ prolongation_status: "negotiate" }),
      ]),
    ).toBe("2 z decyzją o końcu · 1 bez decyzji o przedłużeniu");
  });
});

describe("sortowanie okna", () => {
  it("brak daty na początku (pusty napis), przy tej samej dacie większa marża, brak marży na końcu", () => {
    const sorted = sortWindow(
      [
        wc({ id: 1, end_date: "2027-01-01", rate_unit: "monthly" }),
        wc({ id: 2, end_date: "2027-01-01", rate_client: null }),
        wc({ id: 3, end_date: "2027-01-01", rate_unit: "monthly", rate_client: 500 }),
        wc({ id: 4, end_date: null }),
      ],
      "end_date",
    );
    expect(sorted.map((c) => c.id)).toEqual([4, 3, 1, 2]);
  });
  it("najbliższy koniec na osobę; osoba bez id pomijana", () => {
    const map = endingByPerson([
      wc({ id: 1, candidate_id: 10, end_date: "2027-02-01" }),
      wc({ id: 2, candidate_id: 10, end_date: "2026-12-31" }),
      wc({ id: 3, candidate_id: null, end_date: "2026-11-30" }),
    ]);
    expect([...map.keys()]).toEqual([10]);
    expect(map.get(10)?.id).toBe(2);
  });
});

describe("compareNullable / nextSort", () => {
  it("puste na końcu w obu kierunkach; napisy po polsku; liczby z kierunkiem", () => {
    expect(compareNullable(null, "", "asc")).toBe(0);
    expect(compareNullable(null, 1, "desc")).toBe(1);
    expect(compareNullable(1, undefined, "asc")).toBe(-1);
    expect(compareNullable("Ćma", "Dąb", "asc")).toBeLessThan(0);
    expect(compareNullable(1, 2, "desc")).toBeGreaterThan(0);
    expect(compareNullable(0, 2, "asc")).toBeLessThan(0);
  });
  it("odwrócenie i nowa kolumna", () => {
    expect(nextSort({ key: "margin", dir: "desc" }, "margin")).toEqual({ key: "margin", dir: "asc" });
    expect(nextSort({ key: "margin", dir: "asc" }, "margin")).toEqual({ key: "margin", dir: "desc" });
    expect(nextSort({ key: "margin", dir: "asc" }, "name")).toEqual({ key: "name", dir: "asc" });
  });
});

describe("raport klientów", () => {
  const ending = [wc({ id: 1, client_id: 100 }), wc({ id: 2, client_id: 300, client_name: null })];
  const starting = [wc({ id: 3, client_id: 200, client_name: "Nowa Firma Testowa" }), wc({ id: 4, client_id: 300 })];

  it("braki FX ukrywają kwoty; brak id i nazwy; klienci tylko z okna dostają własne wiersze", () => {
    const rows = buildClientReport(
      [
        mr({ client_id: 100, client_name: "Firma Testowa", fx_missing: true, contracts_without_cost_leg: 2 }),
        mr({ contracts_without_revenue_leg: 1 }),
      ],
      ending,
      starting,
    );
    expect(rows[0]).toMatchObject({ revenue: null, margin: null, pct: null, fxMissing: true, withoutCost: 2 });
    expect(rows[0].ending.map((c) => c.id)).toEqual([1]);
    expect(rows[1]).toMatchObject({ clientId: 0, name: "—", withoutRevenue: 1, ending: [], starting: [] });
    expect(rows.slice(2).map((r) => [r.clientId, r.name, r.contracts])).toEqual([
      [300, "—", null],
      [200, "Nowa Firma Testowa", null],
    ]);
    expect(rows[2].ending.map((c) => c.id)).toEqual([2]);
    expect(rows[2].starting.map((c) => c.id)).toEqual([4]);
  });

  it("sortowanie po każdej kolumnie, puste na końcu, remis po nazwie", () => {
    const rows = buildClientReport(
      [
        mr({ client_id: 100, client_name: "Beta", active_contracts: 2, margin_pct: 10 }),
        mr({ client_id: 101, client_name: "Alfa", active_contracts: 2, total_monthly_revenue: 9000 }),
      ],
      [wc({ client_id: 100 })],
      [wc({ client_id: 200, client_name: "Gamma" })],
    );
    const by = (key: ClientSortKey, dir: "asc" | "desc" = "desc") =>
      sortClientReport(rows, { key, dir }).map((r) => r.name);
    expect(by("name", "asc")).toEqual(["Alfa", "Beta", "Gamma"]);
    expect(by("contracts")).toEqual(["Alfa", "Beta", "Gamma"]);
    expect(by("revenue")).toEqual(["Alfa", "Beta", "Gamma"]);
    expect(by("margin")).toEqual(["Alfa", "Beta", "Gamma"]);
    expect(by("pct")).toEqual(["Alfa", "Beta", "Gamma"]);
    expect(by("ending")).toEqual(["Beta", "Alfa", "Gamma"]);
    expect(by("starting")).toEqual(["Gamma", "Alfa", "Beta"]);
  });

  it("sortowanie osób po każdej kolumnie; FX i brak nazwy na końcu", () => {
    const rows = [
      mr({ candidate_id: 1, candidate_name: "Anna Przykładowa", total_monthly_revenue: 100, margin_pct: 5 }),
      mr({ candidate_id: 2, candidate_name: "Jan Testowy", fx_missing: true, active_contracts: 3 }),
      mr({ candidate_name: undefined, total_monthly_margin: 50 }),
    ];
    const ends = endingByPerson([wc({ candidate_id: 2, end_date: "2026-12-31" })]);
    const by = (key: PersonSortKey, dir: "asc" | "desc" = "desc") =>
      sortPeopleReport(rows, { key, dir }, ends).map((r) => r.candidate_id ?? null);
    expect(by("name", "asc")).toEqual([1, 2, null]);
    expect(by("contracts")).toEqual([2, null, 1]);
    expect(by("revenue")).toEqual([null, 1, 2]);
    expect(by("margin")).toEqual([1, null, 2]);
    expect(by("pct")).toEqual([null, 1, 2]);
    expect(by("ending", "asc")).toEqual([2, null, 1]);
  });
});

describe("prognoza", () => {
  it("etykieta miesiąca: zły format daje zapas, grudzień i styczeń po polsku", () => {
    expect(forecastMonthLabel("2026-13x", "Dec 2026")).toBe("Dec 2026");
    expect(forecastMonthLabel("", "—")).toBe("—");
    expect(forecastMonthLabel("2026-12", "Dec 2026")).toMatch(/^gru 2026$/);
    expect(forecastMonthLabel("2027-01", "Jan 2027")).toMatch(/^sty 2027$/);
  });
  it("oś: pusta seria, płaska zerowa, płaska duża, ujemne", () => {
    expect(forecastAxis([])).toEqual({ hi: 1, lo: 0 });
    expect(forecastAxis([0, 0])).toEqual({ hi: 0.6, lo: -1.4 });
    const flat = forecastAxis([1000, 1000]);
    expect(flat.hi).toBeCloseTo(1006);
    expect(flat.lo).toBeCloseTo(986);
    const neg = forecastAxis([-100, 100]);
    expect(neg.hi).toBeCloseTo(220);
    expect(neg.lo).toBeCloseTo(-180);
  });
  it("zmiana: mniej niż dwa miesiące = null, start od zera bez procentu, ujemny start", () => {
    const m = (margin: number) => ({ month: "2026-12", month_label: "", revenue: 0, margin, active_count: 0 });
    expect(forecastChange([])).toBeNull();
    expect(forecastChange([m(1)])).toBeNull();
    expect(forecastChange([m(0), m(100)])).toEqual({ change: 100, pct: null });
    expect(forecastChange([m(-100), m(-50)])).toEqual({ change: 50, pct: 50 });
  });
});
