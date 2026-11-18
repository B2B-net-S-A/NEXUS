import { describe, expect, it } from "vitest";

import { basisNote } from "@/components/rada/PulpitFinance";
import { monthTable, selectableYears } from "@/components/rada/pulpit-months";
import type { BoardOutlook, BoardSummary } from "@/lib/api/supervisory-board";

function month(year: number, m: number, sales: number, complete = true) {
  return { year, month: m, sales, costs: sales * 0.9, contractors: sales * 0.8, costs_complete: complete, sales_complete: complete };
}

function summary(over: Partial<BoardSummary> = {}): BoardSummary {
  return {
    source: { kind: "invoices", first_date: null, last_date: null },
    years: [],
    months: [
      ...Array.from({ length: 12 }, (_, i) => month(2098, i + 1, 10)),
      month(2099, 1, 11),
      month(2099, 2, 12),
      month(2099, 3, 2, false),
    ],
    budgets: { "2099": [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10] },
    ytd: { sales_months: 2, result_months: 2 },
    top_clients: { year: 2098, items: [] },
    orders: { active: 0, ending: 0, potential_month: null, ending_potential_month: null, without_rate: 0, year_end: "2099-12-31" },
    krs_missing: [],
    documents_without_file: 0,
    ...over,
  };
}

describe("tabela miesięcy pulpitu", () => {
  it("wykonanie, budżet i odchylenia tylko z miesięcy z kompletem faktur", () => {
    const rows = monthTable(summary(), 2099);
    expect(rows.map((r) => r.label)).toEqual([
      "Wykonanie 2098",
      "Budżet 2099",
      "Wykonanie 2099",
      "Odchylenie od budżetu",
      "Odchylenie od 2098",
    ]);
    const vsBudget = rows[3];
    expect(vsBudget.cells[0]).toEqual({ value: 1, pct: 10 });
    expect(vsBudget.cells[1]).toEqual({ value: 2, pct: 20 });
    // Marzec bez kompletu faktur: kursywa w wykonaniu, bez odchylenia.
    expect(rows[2].cells[2]).toEqual({ value: 2, partial: true });
    expect(vsBudget.cells[2].value).toBeNull();
    // „Razem” porównuje te same dwa miesiące.
    expect(rows[2].total.value).toBe(23);
    expect(rows[1].total.value).toBe(20);
    expect(vsBudget.total).toEqual({ value: 3, pct: 15 });
    expect(rows[4].total).toEqual({ value: 3, pct: 15 });
  });

  it("miesiąc bez kompletu i bez żadnej faktury sprzedaży to kreska, nie „0,0”", () => {
    // Produkcja 18.11.2026: październik i listopad przed importem faktur pokazywały 0,0.
    const data = summary({ months: [...summary().months, month(2099, 4, 0, false)] });
    const current = monthTable(data, 2099).find((r) => r.key === "current")!;
    expect(current.cells[3]).toEqual({ value: null, partial: true });
    expect(current.cells[2]).toEqual({ value: 2, partial: true });
  });

  it("bez budżetu nie ma wierszy budżetu, rok następny pokazuje się, gdy ma budżet", () => {
    const rows = monthTable(summary({ budgets: {} }), 2099);
    expect(rows.map((r) => r.key)).toEqual(["previous", "current", "vs-previous"]);
    expect(selectableYears(summary(), 2099)).toEqual([2099, 2098]);
    expect(selectableYears(summary({ budgets: { "2100": Array(12).fill(12) } }), 2099)).toEqual([2099, 2098, 2100].sort((a, b) => b - a));
  });
});

describe("podpis bazy wyceny", () => {
  it("bez sprawozdania odsyła do Analizy", () => {
    const outlook = { current: { base_year: null, ebitda: null, net_debt: null }, profit_shift_applied: false, profit_window: null } as unknown as BoardOutlook;
    expect(basisNote(outlook)).toContain("zakładce Analiza");
  });

  it("z przesunięciem z faktur", () => {
    const outlook = {
      current: { base_year: 2098, ebitda: 12, ebitda_base: 10, ebitda_shift: 2, net_debt: -3 },
      profit_shift_applied: true,
      profit_window: { from: "11.2098", to: "10.2099" },
    } as unknown as BoardOutlook;
    expect(basisNote(outlook)).toBe(
      "EBITDA 12,0 mln = 2098 ze sprawozdania 10,0 mln + 2,0 mln zmiany zysku brutto z faktur (11.2098–10.2099 wobec 2098). Dług netto -3,0 mln.",
    );
  });
});
