import { describe, expect, it } from "vitest";

import { previewCostEntry, settleCostRows } from "../cost-consumption";

describe("settleCostRows", () => {
  it("schodzi z jednej puli w kolejności miesiąc, linia", () => {
    const result = settleCostRows(60000, [
      { order_id: 2, period_month: "2026-07", invoice_amount: 6000 },
      { order_id: 1, period_month: "2026-07", invoice_amount: 8000 },
      { order_id: 1, period_month: "2026-08", invoice_amount: 8000 },
    ]);
    expect(result.remaining).toBe(38000);
    expect(result.unsettledTotal).toBe(0);
  });

  it("reszta nie spada poniżej zera, nadwyżka zostaje na wierszu", () => {
    const result = settleCostRows(10000, [{ order_id: 1, period_month: "2026-10", invoice_amount: 12000 }]);
    expect(result.remaining).toBe(0);
    expect(result.unsettled.get("1|2026-10")).toBe(2000);
  });
});

describe("previewCostEntry", () => {
  it("przykład z ticketu: wrzesień 1 540 zł z 37 850 zł", () => {
    const preview = previewCostEntry(37850, [], { orderId: 844, periodMonth: "2026-09", amount: 1540 });
    expect(preview.remainingAfter).toBe(36310);
    expect(preview.overBy).toBe(0);
    expect(preview.overflowRows).toEqual([]);
  });

  it("przekroczenie liczy różnicę ponad resztę i wskazuje wiersz", () => {
    const rows = [{ order_id: 844, period_month: "2026-09", invoice_amount: 1540 }];
    const preview = previewCostEntry(37850, rows, { orderId: 844, periodMonth: "2026-10", amount: 38000 });
    expect(preview.remainingAfter).toBe(0);
    expect(preview.overBy).toBe(1690);
    expect(preview.overflowRows).toEqual([{ order_id: 844, period_month: "2026-10", invoice_amount: 38000 }]);
  });

  it("edycja nadpisuje miesiąc, nie dokłada", () => {
    const rows = [{ order_id: 1, period_month: "2026-09", invoice_amount: 9000 }];
    const preview = previewCostEntry(10000, rows, { orderId: 1, periodMonth: "2026-09", amount: 9500 });
    expect(preview.remainingAfter).toBe(500);
    expect(preview.overBy).toBe(0);
  });

  it("wpis za wcześniejszy miesiąc przesuwa nadwyżkę na późniejszą fakturę innej osoby", () => {
    const rows = [{ order_id: 2, period_month: "2026-10", invoice_amount: 8000 }];
    const preview = previewCostEntry(10000, rows, { orderId: 1, periodMonth: "2026-09", amount: 5000 });
    expect(preview.overBy).toBe(3000);
    expect(preview.overflowRows.map((row) => row.order_id)).toEqual([2]);
  });

  it("już przekroczone zamówienie: liczy tylko przyrost nadwyżki", () => {
    const rows = [{ order_id: 1, period_month: "2026-08", invoice_amount: 12000 }];
    const preview = previewCostEntry(10000, rows, { orderId: 1, periodMonth: "2026-09", amount: 500 });
    expect(preview.overBy).toBe(500);
  });

  it("grosze nie dają fałszywego przekroczenia", () => {
    const rows = [
      { order_id: 1, period_month: "2026-07", invoice_amount: 0.1 },
      { order_id: 1, period_month: "2026-08", invoice_amount: 0.2 },
    ];
    const preview = previewCostEntry(0.6, rows, { orderId: 1, periodMonth: "2026-09", amount: 0.3 });
    expect(preview.overBy).toBe(0);
    expect(preview.remainingAfter).toBe(0);
  });
});
