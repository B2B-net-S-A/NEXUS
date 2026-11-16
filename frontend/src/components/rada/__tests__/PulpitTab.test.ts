import { describe, expect, it } from "vitest";

import { attentionItems } from "@/components/rada/PulpitTab";
import type { BoardSummary } from "@/lib/api/supervisory-board";

function summary(over: Partial<BoardSummary> = {}): BoardSummary {
  return {
    source: { kind: "invoices", first_date: "2099-01-02", last_date: "2099-11-16" },
    years: [],
    months: [],
    ytd: { sales_months: 10, sales: 98.8, sales_previous: 95.6, result_months: 9, result: 5.0, result_pct: 5.8, result_previous: 6.9, result_previous_pct: 8.1 },
    top_clients: { year: 2098, items: [{ name: "Klient A", sales: 73.5, share: 65.1 }] },
    orders: { active: 507, ending: 286, potential_month: 13.7, ending_potential_month: 7.6, without_rate: 1, year_end: "2099-12-31" },
    krs_missing: [{ year: 2098, missing: ["audit_opinion"] }],
    documents_without_file: 56,
    ...over,
  };
}

describe("Do uwagi Rady", () => {
  it("spadek wyniku, przedłużenia, koncentracja, KRS i skany", () => {
    const titles = attentionItems(summary(), 2099).map((a) => a.title);
    expect(titles).toEqual([
      "Wynik z faktur niższy niż rok wcześniej (I–IX)",
      "286 z 507 kontraktów: umowa albo zamówienie kończy się do 31.12.2099",
      "Klient A: 65,1% sprzedaży 2098",
      "KRS: brak opinii biegłego za 2098",
      "56 dokumentów bez skanu",
    ]);
  });

  it("poniżej progów nic nie podnosi", () => {
    const quiet = summary({
      ytd: { sales_months: 3, result_months: 3, result_pct: 8.0, result_previous_pct: 8.5 },
      top_clients: { year: 2098, items: [{ name: "B", sales: 1, share: 20 }] },
      orders: { active: 100, ending: 10, potential_month: 1, ending_potential_month: 0.1, without_rate: 0, year_end: "2099-12-31" },
      krs_missing: [],
      documents_without_file: 0,
    });
    expect(attentionItems(quiet, 2099)).toEqual([]);
  });
});
