import { describe, expect, it } from "vitest";

import {
  creditCapacity,
  equityValue,
  latestFullYear,
  missingYears,
  parseAmount,
  ratioTone,
} from "../AnalysisTab";
import type { AnalysisView, StatementYear } from "@/lib/api/supervisory-board";

function year(y: number, partial: number | null = null): StatementYear {
  return {
    year: y,
    source: partial === null ? "xml" : "ledger",
    source_label: "",
    period_start: null,
    period_end: null,
    document_id: null,
    schema_name: null,
    note: null,
    amounts: {},
    raw_count: 0,
    partial_months: partial,
    updated_at: null,
    metrics: {} as StatementYear["metrics"],
    growth: { revenue: null, ebitda: null, net_profit: null },
  };
}

describe("analiza Rady — wyliczenia", () => {
  it("bierze ostatni pełny rok, nie rok z księgi w trakcie", () => {
    expect(latestFullYear([year(2024), year(2025), year(2026, 10)])?.year).toBe(2025);
    expect(latestFullYear([year(2026, 10)])).toBeNull();
  });

  it("wolny limit kredytu odejmuje dług netto, gotówka netto go zwiększa", () => {
    expect(creditCapacity(10, 4, 3)).toEqual({ maxNetDebt: 30, headroom: 26 });
    expect(creditCapacity(10, -5, 3)?.headroom).toBe(35);
    expect(creditCapacity(-1, 0, 3)).toBeNull();
    expect(creditCapacity(null, 0, 3)).toBeNull();
  });

  it("wartość kapitału = EV − dług netto", () => {
    expect(equityValue(8, 2, 6)).toEqual({ ev: 48, equity: 46 });
    expect(equityValue(8, -4, 6)?.equity).toBe(52);
    expect(equityValue(0, 0, 6)).toBeNull();
  });

  it("ocenia wskaźnik względem przedziału, brak danych jest neutralny", () => {
    const norm = { label: "", formula: "", good: [1.2, 2] as [number, number] };
    expect(ratioTone(1.5, norm)).toBe("good");
    expect(ratioTone(0.9, norm)).toBe("bad");
    expect(ratioTone(null, norm)).toBe("neutral");
  });

  it("brakujące lata pomijają rok z księgi w trakcie", () => {
    const view = { years: [year(2024), year(2026, 9)], expected_years: [2023, 2024, 2025] } as AnalysisView;
    expect(missingYears(view)).toEqual([2023, 2025]);
  });

  it("czyta kwoty z PDF ze spacjami i przecinkiem", () => {
    expect(parseAmount("120 450 300,12")).toBe(120450300.12);
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("12a")).toBe("invalid");
  });
});
