import { describe, expect, it } from "vitest";

import {
  agingRows,
  amountCents,
  amountProblem,
  autoLabel,
  autoMessage,
  autoTotal,
  daysLabel,
  docLabel,
  pairsLabel,
  periodAsOf,
  positionsLabel,
  readAccount,
  readAsOf,
  selection,
  settleBlocker,
  settleMessage,
} from "@/components/accounting/settlements-model";
import type { SettlementItem } from "@/lib/api/accounting-settlements";

function item(lineId: number, direction: "debit" | "credit", remaining: number): SettlementItem {
  return {
    line_id: lineId,
    document_id: lineId,
    doc_type: direction === "debit" ? "FVS" : "WB",
    number: `FS ${lineId}/2026`,
    op_date: "2026-03-10",
    due_on: null,
    overdue_days: 0,
    description: "",
    direction,
    value: remaining,
    remaining,
    currency: "PLN",
    amount_cur: null,
    settlements: [],
  };
}

describe("rozrachunki — zaznaczenie i kwota", () => {
  const open = [item(1, "debit", 123_000), item(2, "debit", 50_000), item(3, "credit", 110_700)];

  it("suma zaznaczonych i kwota do rozliczenia od najstarszych", () => {
    const chosen = selection(open, new Set([1, 2, 3]));
    expect(chosen.debitSum).toBe(173_000);
    expect(chosen.creditSum).toBe(110_700);
    expect(chosen.amount).toBe(110_700);
    expect(chosen.partial).toBe(false);
    expect(selection(open, new Set([1, 3])).partial).toBe(true);
    expect(selection(open, new Set([1])).amount).toBe(0);
  });

  it("przycisk mówi, czego brakuje", () => {
    expect(settleBlocker(selection(open, new Set()), true)).toBe("Zaznacz pozycje po stronie Wn i Ma.");
    expect(settleBlocker(selection(open, new Set([1])), true)).toBe("Zaznacz też pozycję po stronie Ma.");
    expect(settleBlocker(selection(open, new Set([3])), true)).toBe("Zaznacz też pozycję po stronie Wn.");
    expect(settleBlocker(selection(open, new Set([1, 3])), true)).toBeNull();
    expect(settleBlocker(selection(open, new Set([1, 3])), false)).toMatch(/Księgowi/);
  });

  it("kwota częściowa: grosze, zero, minus i limit", () => {
    expect(amountCents("1 107,50")).toBe(110_750);
    expect(amountCents("100")).toBe(10_000);
    expect(amountCents("-5")).toBeNull();
    expect(amountCents("0")).toBeNull();
    expect(amountProblem("", 1_000)).toBeNull();
    expect(amountProblem("abc", 1_000)).toMatch(/większą od zera/);
    expect(amountProblem("20,00", 1_000)).toBe("Najwyżej 10,00 zł — tyle zostało do rozliczenia.");
    expect(amountProblem("10,00", 1_000)).toBeNull();
  });
});

describe("rozrachunki — etykiety", () => {
  it("automat: suma i tylko niezerowe sposoby", () => {
    const counts = { bank: 3, correction: 0, zero: 2 };
    expect(autoTotal(counts)).toBe(5);
    expect(autoLabel(counts)).toBe("z wyciągów 3 · salda zerowe 2");
    expect(autoMessage({ ...counts, created: 0, amount: 0 })).toBe("Automat nie znalazł nic do rozliczenia.");
    expect(autoMessage({ ...counts, created: 5, amount: 123_456 })).toBe(
      "Automat rozliczył 1 234,56 zł: z wyciągów 3 · salda zerowe 2.",
    );
  });

  it("odmiana i dokument", () => {
    expect(positionsLabel(1)).toBe("1 pozycja");
    expect(positionsLabel(3)).toBe("3 pozycje");
    expect(positionsLabel(12)).toBe("12 pozycji");
    expect(pairsLabel(2)).toBe("2 pary");
    expect(pairsLabel(5)).toBe("5 par");
    expect(settleMessage(10_000, 1)).toBe("Rozliczono 100,00 zł (1 para pozycji).");
    expect(daysLabel(1)).toBe("1 dzień");
    expect(daysLabel(16)).toBe("16 dni");
    expect(docLabel({ doc_type: "FVS", number: "FS 1/2026" })).toBe("FVS FS 1/2026");
    expect(docLabel({ doc_type: "PK", number: "PK 2/03/2026" })).toBe("PK 2/03/2026");
  });

  it("wiekowanie obu stron w jednej tabeli", () => {
    const rows = agingRows({
      receivable: [
        { key: "current", label: "w terminie", amount: 5, count: 1 },
        { key: "none", label: "bez terminu", amount: 0, count: 0 },
      ],
      payable: [{ key: "none", label: "bez terminu", amount: 7, count: 1 }],
    });
    expect(rows).toEqual([
      { key: "current", label: "w terminie", receivable: 5, payable: 0 },
      { key: "none", label: "bez terminu", receivable: 0, payable: 7 },
    ]);
  });

  it("na dzień: koniec miesiąca z nagłówka, w bieżącym miesiącu dziś", () => {
    expect(periodAsOf(2026, 10, "2026-11-14")).toBe("2026-10-31");
    expect(periodAsOf(2026, 11, "2026-11-14")).toBe("2026-11-14");
    expect(periodAsOf(2028, 2, "2028-03-01")).toBe("2028-02-29");
    expect(periodAsOf(2026, 12, "2026-11-14")).toBe("2026-11-14");
  });

  it("konto i dzień z adresu", () => {
    expect(readAccount("?account=200-1234&as_of=2026-03-31")).toBe("200-1234");
    expect(readAccount("?account=200%201")).toBeNull();
    expect(readAsOf("?as_of=2026-03-31")).toBe("2026-03-31");
    expect(readAsOf("?as_of=31.03.2026")).toBeNull();
  });
});
