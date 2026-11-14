import { describe, expect, it } from "vitest";

import type { LedgerConfig } from "@/lib/api/accounting";

import {
  activeTab,
  analyticsLabel,
  checkDraft,
  findPeriod,
  gr,
  monthTitle,
  newLine,
  parseAmount,
  readPeriod,
  shiftPeriod,
  short,
  toGrosze,
  visibleTabs,
  type DraftLine,
} from "../ledger-model";

function line(side: "debit" | "credit", account: string, amount: string): DraftLine {
  return { ...newLine(side), account, amount };
}

describe("kwoty", () => {
  it("formatuje grosze z grupowaniem i minusem", () => {
    expect(gr(123456)).toBe("1 234,56");
    expect(gr(-5)).toBe("−0,05");
    expect(gr(0)).toBe("0,00");
    expect(gr(null)).toBe("—");
    expect(short(642_378_916_9)).toBe("64,2 mln");
  });

  it("czyta kwotę z formularza: spacje, przecinek, minus storna", () => {
    expect(parseAmount("1 234,5")).toBe("1234.50");
    expect(parseAmount("−12,30")).toBe("-12.30");
    expect(parseAmount("0,00")).toBeNull();
    expect(parseAmount("1,234")).toBeNull();
    expect(parseAmount("abc")).toBeNull();
    expect(parseAmount("")).toBeNull();
  });

  it("zamienia tekst API na grosze", () => {
    expect(toGrosze("1234.56")).toBe(123456);
    expect(toGrosze("-12.30")).toBe(-1230);
    expect(toGrosze("7")).toBe(700);
  });
});

describe("checkDraft", () => {
  it("bilansuje fakturę i buduje ciało żądania", () => {
    const result = checkDraft([
      line("debit", "402-203", "1000"),
      line("debit", "221", "230,00"),
      line("credit", "201-2-1042", "1 230"),
    ]);
    expect(result.problems).toEqual([]);
    expect(result.balanced).toBe(true);
    expect(result.debit).toBe(123000);
    expect(result.lines.map((item) => item.amount)).toEqual(["1000.00", "230.00", "1230.00"]);
  });

  it("mówi o różnicy sum jak serwer", () => {
    const result = checkDraft([line("debit", "402-203", "10"), line("credit", "131-1", "9,99")]);
    expect(result.balanced).toBe(false);
    expect(result.problems).toEqual(["Suma Wn (10,00 zł) różni się od sumy Ma (9,99 zł)."]);
  });

  it("pomija puste wiersze, ale wymaga dwóch pozycji", () => {
    const result = checkDraft([line("debit", "402-203", "10"), line("credit", "", "")]);
    expect(result.problems).toEqual(["Dokument potrzebuje co najmniej dwóch pozycji."]);
  });

  it("wskazuje pozycję bez konta albo z błędną kwotą", () => {
    const result = checkDraft([line("debit", "", "10"), line("credit", "131-1", "x")]);
    expect(result.problems).toEqual([
      "Pozycja 1: podaj konto.",
      "Pozycja 2: podaj kwotę (np. 1234,56).",
    ]);
  });

  it("przyjmuje storno czerwone na jednej stronie", () => {
    const result = checkDraft([line("debit", "402-203", "500"), line("debit", "490", "-500")]);
    expect(result.problems).toEqual([]);
    expect(result.balanced).toBe(true);
  });
});

describe("okres z adresu", () => {
  it("bierze rok i miesiąc z adresu, inaczej dzisiejszy miesiąc firmy", () => {
    expect(readPeriod("?year=2026&month=10", "2026-11-14")).toEqual({ year: 2026, month: 10 });
    expect(readPeriod("?year=1999&month=13", "2026-11-14")).toEqual({ year: 2026, month: 11 });
    expect(readPeriod("", "2027-01-02")).toEqual({ year: 2027, month: 1 });
  });

  it("przesuwa miesiąc przez granicę roku", () => {
    expect(shiftPeriod({ year: 2026, month: 12 }, 1)).toEqual({ year: 2027, month: 1 });
    expect(shiftPeriod({ year: 2026, month: 1 }, -1)).toEqual({ year: 2025, month: 12 });
    expect(monthTitle(2026, 10)).toBe("Październik 2026");
  });
});

const CONFIG: LedgerConfig = {
  open: true,
  modules: [
    { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
    { key: "bank", label: "Bank", replaces: "import XML", stage: "K4", built: false, enabled: false, open: true },
  ],
  me: { admin: false, approver: true, payroll: false },
  accountants: null,
  sales_accounts: { receivable_account: "200", revenue_account: "", vat_account: "222" },
  years: [
    {
      id: 1,
      year: 2026,
      mode: "symfonia",
      mode_label: "Symfonia FK — NEXUS przygotowuje paczki",
      status: "open",
      journal_entries: 3,
      periods: [
        {
          id: 10,
          month: 10,
          starts_on: "2026-10-01",
          ends_on: "2026-10-31",
          status: "open",
          closed_at: null,
          reopened_at: null,
          reopen_reason: null,
          drafts: 1,
          approved: 3,
        },
      ],
    },
  ],
  today: "2026-11-14",
  doc_types: [],
  year_modes: [],
  account_kinds: [],
  account_types: [],
  dictionaries: [],
};

describe("zakładki i okres", () => {
  it("pokazuje zakładki modułów otwartych dla osoby i zawsze Ustawienia", () => {
    expect(visibleTabs(CONFIG).map((tab) => tab.label)).toEqual([
      "Miesiąc",
      "Źródła",
      "Dokumenty",
      "Obroty i salda",
      "Plan kont",
      "Ustawienia",
    ]);
    expect(visibleTabs({ ...CONFIG, modules: [] }).map((tab) => tab.label)).toEqual(["Ustawienia"]);
    expect(visibleTabs(undefined)).toEqual([]);
  });

  it("rozpoznaje zakładkę po ścieżce", () => {
    expect(activeTab("/accounting").label).toBe("Miesiąc");
    expect(activeTab("/accounting/documents").label).toBe("Dokumenty");
    expect(activeTab("/accounting/sources").label).toBe("Źródła");
    expect(activeTab("/accounting/chart/x").label).toBe("Plan kont");
    expect(activeTab(null).label).toBe("Miesiąc");
  });

  it("znajduje rok i okres", () => {
    expect(findPeriod(CONFIG, { year: 2026, month: 10 }).period?.drafts).toBe(1);
    expect(findPeriod(CONFIG, { year: 2026, month: 9 }).period).toBeNull();
    expect(findPeriod(CONFIG, { year: 2027, month: 1 }).year).toBeNull();
  });
});

describe("odmiana", () => {
  it("odmienia konta analityczne", () => {
    expect(analyticsLabel(1)).toBe("1 konto analityczne");
    expect(analyticsLabel(3)).toBe("3 konta analityczne");
    expect(analyticsLabel(5)).toBe("5 kont analitycznych");
    expect(analyticsLabel(12)).toBe("12 kont analitycznych");
    expect(analyticsLabel(22)).toBe("22 konta analityczne");
  });
});
