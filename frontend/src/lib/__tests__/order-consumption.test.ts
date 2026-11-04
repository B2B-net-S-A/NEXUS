import { describe, expect, it } from "vitest";

import {
  MAX_MONTH_OPTIONS,
  consumptionMonthOptions,
  monthLabelPl,
} from "@/lib/order-consumption";

const TODAY = new Date(2026, 8, 25); // 25.09.2026

describe("consumptionMonthOptions", () => {
  it("od startu do bieżącego miesiąca, od najnowszego", () => {
    expect(consumptionMonthOptions("2026-06-15", null, TODAY).map((o) => o.value)).toEqual([
      "2026-09",
      "2026-08",
      "2026-07",
      "2026-06",
    ]);
  });

  it("koniec udziału przed dziś ucina listę na miesiącu końca", () => {
    expect(
      consumptionMonthOptions("2026-05-01", "2026-08-31", TODAY).map((o) => o.value),
    ).toEqual(["2026-08", "2026-07", "2026-06", "2026-05"]);
  });

  it("koniec w przyszłości nie daje miesięcy przyszłych", () => {
    expect(consumptionMonthOptions("2026-08-01", "2027-03-31", TODAY)[0].value).toBe("2026-09");
  });

  it("przejście przez rok", () => {
    expect(
      consumptionMonthOptions("2025-11-10", "2026-01-31", TODAY).map((o) => o.value),
    ).toEqual(["2026-01", "2025-12", "2025-11"]);
  });

  it("bez startu — ostatnie 12 miesięcy", () => {
    const options = consumptionMonthOptions(null, null, TODAY);
    expect(options).toHaveLength(12);
    expect(options[11].value).toBe("2025-10");
  });

  it("długie zamówienie bezterminowe — najwyżej MAX_MONTH_OPTIONS pozycji", () => {
    expect(consumptionMonthOptions("2019-01-01", null, TODAY)).toHaveLength(MAX_MONTH_OPTIONS);
  });

  it("koniec przed startem daje choć miesiąc startu, nie pustą listę", () => {
    expect(consumptionMonthOptions("2026-09-01", "2026-08-31", TODAY).map((o) => o.value)).toEqual([
      "2026-09",
    ]);
  });

  it("etykiety po polsku", () => {
    expect(consumptionMonthOptions("2026-08-01", "2026-08-31", TODAY)[0].label).toBe(
      "sierpień 2026",
    );
    expect(monthLabelPl("2026-02")).toBe("luty 2026");
  });
});
