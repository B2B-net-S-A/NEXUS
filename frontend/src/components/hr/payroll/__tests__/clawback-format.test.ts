import { describe, expect, it } from "vitest";

import type { BonusClawback, SettlementMonth } from "@/lib/api/hr-payroll";

import { bonusMonths, monthAssigned, monthClawback, monthTotal } from "../../me/bonus-months";
import { settlementLineText } from "../../me/MySettlementCard";
import {
  clawbackActive,
  clawbackProgress,
  clawbackReason,
  clawbackRemaining,
} from "../clawback-format";

/** Gwarancja premii DL (05.11.2026): dane fikcyjne. */
function claw(overrides: Partial<BonusClawback> = {}): BonusClawback {
  return {
    id: 1,
    bonus_id: 10,
    recipient_user_id: 5,
    recipient_name: "Anna Przykładowa",
    contract_id: 7,
    description: "Premia DL — placement: Jan P. (Firma)",
    bonus_period: "2026-10",
    amount: "1512.00",
    currency: "PLN",
    settled: "0.00",
    remaining: "1512.00",
    refund_due: null,
    origin: "automatic",
    status: "open",
    contract_start: "2026-11-03",
    ended_on: "2026-11-05",
    deduct_from: "2026-11-01",
    guarantee_until: "2027-11-02",
    note: null,
    cancel_reason: null,
    created_at: "2026-11-05T10:00:00+01:00",
    ...overrides,
  };
}

describe("clawback-format", () => {
  it("liczy resztę per walutę, bez spłaconych i anulowanych", () => {
    const items = [
      claw(),
      claw({ id: 2, remaining: "200.00" }),
      claw({ id: 3, status: "settled", remaining: "0.00", settled: "1512.00" }),
      claw({ id: 4, currency: "EUR", remaining: "50.00" }),
    ];
    expect(clawbackRemaining(items)).toEqual({ PLN: 1712, EUR: 50 });
  });

  it("anulowany po potrąceniu zostaje na liście jako „do oddania”", () => {
    const refund = claw({ status: "cancelled", remaining: "0.00", settled: "300.00", refund_due: "300.00" });
    expect(clawbackActive(refund)).toBe(true);
    expect(clawbackActive(claw({ status: "settled", remaining: "0.00" }))).toBe(false);
    expect(clawbackProgress(refund)).toContain("do oddania");
  });

  it("mówi, skąd dług: koniec kontraktu albo powód Płac", () => {
    expect(clawbackReason(claw())).toBe("kontrakt zakończony 05.11.2026 (przed 12 mies.)");
    expect(
      clawbackReason(claw({ origin: "manual", ended_on: null, note: "konsultant odszedł" })),
    ).toBe("Rozliczenia: konsultant odszedł");
    expect(clawbackProgress(claw({ settled: "1000.00", remaining: "512.00" }))).toMatch(
      /^potrącono 1\s?000,00\szł z 1\s?512,00\szł · potrąca się od 11\.2026$/,
    );
  });
});

function month(lines: SettlementMonth["lines"]): SettlementMonth {
  return {
    year: 2026,
    month: 12,
    label: "grudzień 2026",
    final: false,
    hours: "160.00",
    hours_source: "approved",
    timesheet_status: "approved",
    rate_missing: false,
    lines,
  };
}

describe("potrącenie w miesiącu osoby", () => {
  const settled = month([
    {
      currency: "PLN",
      hourly_rate: "50.00",
      hours_amount: "8000.00",
      bonus_total: "0.00",
      clawback_total: "1000.00",
      total: "8000.00",
    },
  ]);

  it("premie przed potrąceniem, potrącenie osobno, razem po potrąceniu", () => {
    const [only] = bonusMonths([], { months: [settled] });
    expect(monthAssigned(only)).toEqual({ PLN: 1000 });
    expect(monthClawback(only)).toEqual({ PLN: 1000 });
    expect(monthTotal(only)).toEqual({ PLN: 8000 });
  });

  it("linia rozliczenia pokazuje premie i potrącenie z gwarancji", () => {
    expect(settlementLineText(settled, settled.lines[0], "b2b")).toMatch(
      /dodatkowe 1\s?000,00\szł · potrącenie z gwarancji −1\s?000,00\szł$/,
    );
  });

  it("linia sprzed gwarancji (bez pola) liczy się jak dotąd", () => {
    const [only] = bonusMonths(
      [],
      { months: [month([{ currency: "PLN", hourly_rate: null, hours_amount: null, bonus_total: "300.00", total: "300.00" }])] },
    );
    expect(monthClawback(only)).toEqual({});
    expect(monthAssigned(only)).toEqual({ PLN: 300 });
  });
});
