import { describe, expect, it } from "vitest";

import type { SettlementMonth } from "@/lib/api/hr-payroll";

import {
  bonusMonths,
  defaultMonth,
  monthAssigned,
  monthBase,
  monthKey,
  monthTotal,
  type BonusMonth,
} from "../bonus-months";
import type { MyBonusItem } from "../overview-format";

function item(overrides: Partial<MyBonusItem> & Pick<MyBonusItem, "key">): MyBonusItem {
  return {
    title: "Pozycja",
    subtitle: "Delivery Lead",
    stages: [],
    amount: "100.00",
    currency: "PLN",
    estimate: false,
    when: "",
    cancelled: false,
    inTransit: false,
    progress: null,
    timeline: "",
    period: { year: 2026, month: 9 },
    ...overrides,
  };
}

function settled(overrides: Partial<SettlementMonth> = {}): SettlementMonth {
  return {
    year: 2026,
    month: 9,
    label: "wrzesień 2026",
    final: false,
    hours: "160.00",
    hours_source: "approved",
    timesheet_status: "approved",
    rate_missing: false,
    lines: [
      { currency: "PLN", hourly_rate: "90.00", hours_amount: "14400.00", bonus_total: "500.00", total: "14900.00" },
    ],
    ...overrides,
  };
}

function only(months: readonly BonusMonth[]): BonusMonth {
  expect(months).toHaveLength(1);
  return months[0];
}

describe("bonusMonths", () => {
  it("układa miesiące od najstarszego, także przez przełom roku", () => {
    const months = bonusMonths(
      [
        item({ key: "a", period: { year: 2027, month: 1 } }),
        item({ key: "b", period: { year: 2026, month: 12 } }),
      ],
      { months: [settled({ year: 2026, month: 11 })] },
    );
    expect(months.map((month) => month.key)).toEqual(["2026-11", "2026-12", "2027-01"]);
    expect(months[0].name).toBe("listopad");
  });

  it("anulowane idą na koniec miesiąca, reszta zachowuje kolejność", () => {
    const month = only(
      bonusMonths(
        [item({ key: "skreslona", cancelled: true }), item({ key: "pierwsza" }), item({ key: "druga" })],
        undefined,
      ),
    );
    expect(month.rows.map((row) => row.key)).toEqual(["pierwsza", "druga", "skreslona"]);
  });
});

describe("kwoty miesiąca", () => {
  it("bierze kwoty serwera, gdy miesiąc ma rozliczenie", () => {
    const month = only(bonusMonths([item({ key: "a", amount: "1.00" })], { months: [settled()] }));
    expect(monthBase(month)).toEqual({ PLN: "14400.00" });
    expect(monthAssigned(month)).toEqual({ PLN: 500 });
    expect(monthTotal(month)).toEqual({ PLN: 14900 });
  });

  it("bez rozliczenia sumuje przyznane, a pomija propozycje, anulowane i brak kwoty", () => {
    const month = only(
      bonusMonths(
        [
          item({ key: "przyznana", amount: "100.00" }),
          item({ key: "druga", amount: "50.50" }),
          item({ key: "w-drodze", amount: "900.00", inTransit: true }),
          item({ key: "anulowana", amount: "700.00", cancelled: true }),
          item({ key: "bez-kwoty", amount: null }),
        ],
        undefined,
      ),
    );
    expect(monthAssigned(month)).toEqual({ PLN: 150.5 });
    expect(monthBase(month)).toEqual({});
    expect(monthTotal(month)).toEqual({ PLN: 150.5 });
  });

  it("otwarty miesiąc bez godzin nie ma podstawy zamiast mieć zero", () => {
    const month = only(
      bonusMonths([], {
        months: [
          settled({
            hours: "0",
            hours_source: "none",
            lines: [{ currency: "PLN", hourly_rate: "90.00", hours_amount: "0.00", bonus_total: "0.00", total: "0.00" }],
          }),
        ],
      }),
    );
    expect(monthBase(month)).toEqual({});
    expect(monthTotal(month)).toEqual({});
  });

  it("zamknięty miesiąc bez godzin to fakt: podstawa 0", () => {
    const month = only(
      bonusMonths([], {
        months: [
          settled({
            final: true,
            hours: "0",
            lines: [{ currency: "PLN", hourly_rate: "90.00", hours_amount: "0.00", bonus_total: "0.00", total: "0.00" }],
          }),
        ],
      }),
    );
    expect(monthBase(month)).toEqual({ PLN: "0.00" });
  });

  it("brak stawki: godziny są, a podstawy nie ma", () => {
    const month = only(
      bonusMonths([], {
        months: [
          settled({
            rate_missing: true,
            lines: [{ currency: "PLN", hourly_rate: null, hours_amount: null, bonus_total: "200.00", total: "200.00" }],
          }),
        ],
      }),
    );
    expect(monthBase(month)).toEqual({});
    expect(monthTotal(month)).toEqual({ PLN: 200 });
  });

  it("dwie waluty liczą się osobno", () => {
    const month = only(
      bonusMonths([], {
        months: [
          settled({
            lines: [
              { currency: "PLN", hourly_rate: "90.00", hours_amount: "14400.00", bonus_total: "0.00", total: "14400.00" },
              { currency: "EUR", hourly_rate: null, hours_amount: null, bonus_total: "300.00", total: "300.00" },
            ],
          }),
        ],
      }),
    );
    expect(monthTotal(month)).toEqual({ PLN: 14400, EUR: 300 });
  });
});

describe("defaultMonth", () => {
  it("wybiera najnowszy miesiąc z kwotą, nie pusty bieżący", () => {
    const months = bonusMonths([item({ key: "w-drodze", inTransit: true, period: { year: 2026, month: 11 } })], {
      months: [
        settled({ month: 10 }),
        settled({
          month: 11,
          hours: "0",
          lines: [{ currency: "PLN", hourly_rate: "90.00", hours_amount: "0.00", bonus_total: "0.00", total: "0.00" }],
        }),
      ],
    });
    expect(defaultMonth(months, "2026-11")).toBe("2026-10");
  });

  it("bez żadnej kwoty zostaje miesiąc bieżący", () => {
    const months = bonusMonths([item({ key: "w-drodze", inTransit: true })], undefined);
    expect(defaultMonth(months, monthKey(2026, 11))).toBe("2026-11");
  });
});
