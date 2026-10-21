import { describe, expect, it } from "vitest";

import { closeConflict, type BonusRow, type MyPayroll } from "@/lib/api/hr-payroll";
import { warsawToday } from "@/lib/warsaw-date";
import { formatMoney } from "@/lib/money";
import { formatIsoDatePl } from "@/lib/date-pl";

import { formFromRules, rulesPayload } from "../BonusRulesCard";
import { myStats } from "../MyBonusesTab";
import { monthState } from "../PayrollMonthsScreen";
import { rateRange } from "../PayrollProfileSection";
import {
  bonusCreatedToast,
  bonusDecision,
  bonusStateLabel,
  formatHours,
  formatTotals,
  parseAmount,
  parseYm,
  progressPercent,
  rateToast,
  timesheetLabel,
  timesheetTone,
  warsawMonth,
  ymSegment,
} from "../payroll-format";

const nbsp = (text: string) => text.replace(/\s/g, " ");

function bonus(overrides: Partial<BonusRow> = {}): BonusRow {
  return {
    id: 1,
    recipient_user_id: 7,
    recipient_name: "Anna Przykładowa",
    proposed_by: null,
    proposed_by_name: null,
    amount: "772.80",
    currency: "PLN",
    category: "delivery_lead",
    category_label: "Delivery Lead",
    period_year: 2026,
    period_month: 9,
    status: "assigned",
    source: "contract_placement",
    contract_id: 3,
    eligible_on: "2026-09-30",
    description: null,
    assigned_by: 2,
    assigned_at: null,
    cancelled_at: null,
    cancel_reason: null,
    edited: false,
    ...overrides,
  };
}

describe("kwoty i godziny po polsku", () => {
  it("formatuje kwotę z tekstu dziesiętnego i walutą", () => {
    expect(nbsp(formatMoney("23652.8"))).toBe("23 652,80 zł");
    expect(nbsp(formatMoney("100", "EUR"))).toBe("100,00 EUR");
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("abc")).toBe("—");
  });

  it("sumy per waluta w jednej linii, zera pominięte (4 cyfry bez spacji — polska norma)", () => {
    expect(nbsp(formatTotals({ PLN: "2300.00", EUR: "100.00", USD: "0.00" }))).toBe(
      "2300,00 zł · 100,00 EUR",
    );
    expect(formatTotals({})).toBe("—");
  });

  it("godziny bez zbędnych zer", () => {
    expect(formatHours("168.00")).toBe("168");
    expect(formatHours("7.50")).toBe("7,5");
  });

  it("kwota z pola formularza: przecinek, spacje, najwyżej dwa miejsca", () => {
    expect(parseAmount("1 234,5")).toBe("1234.5");
    expect(parseAmount("772,80")).toBe("772.80");
    expect(parseAmount("12,345")).toBeNull();
    expect(parseAmount("-5")).toBeNull();
    expect(parseAmount("")).toBeNull();
  });
});

describe("miesiące i daty", () => {
  it("segment adresu w obie strony", () => {
    expect(ymSegment(2026, 9)).toBe("2026-09");
    expect(parseYm("2026-09")).toEqual({ year: 2026, month: 9 });
    expect(parseYm("2026-13")).toBeNull();
    expect(parseYm("wrzesień")).toBeNull();
  });

  it("„dziś” i bieżący miesiąc liczone w Warszawie, nie w UTC", () => {
    // 31.10 23:30 UTC = 1.11 00:30 w Warszawie.
    const lateUtc = new Date(Date.UTC(2026, 9, 31, 23, 30));
    expect(warsawToday(lateUtc)).toBe("2026-11-01");
    expect(warsawMonth(lateUtc)).toBe("2026-11");
  });

  it("data kalendarzowa bez przesunięcia strefy", () => {
    expect(formatIsoDatePl("2026-09-30")).toBe("30.09.2026");
    expect(rateRange({ effective_from: "2026-06-01", effective_to: "2026-08-31" })).toBe(
      "01.06.2026 – 31.08.2026",
    );
    expect(rateRange({ effective_from: "2026-09-01", effective_to: null })).toBe("od 01.09.2026");
  });
});

describe("statusy", () => {
  it("propozycja przed terminem „liczy się”, po terminie czeka na decyzję", () => {
    expect(bonusStateLabel(bonus({ status: "proposed", eligible: false }))).toBe(
      "liczy się do 30.09",
    );
    expect(bonusStateLabel(bonus({ status: "proposed", eligible: true }))).toBe(
      "czeka na zatwierdzenie",
    );
    expect(bonusStateLabel(bonus({ status: "cancelled" }))).toBe("anulowana");
  });

  it("pasek „X z 21 dni roboczych”", () => {
    expect(progressPercent(10, 21)).toBe(48);
    expect(progressPercent(30, 21)).toBe(100);
    expect(progressPercent(null, 21)).toBe(0);
  });

  it("timesheet: słownik i kolory te same co w „Moim miesiącu” i „Moim zespole”", () => {
    expect(timesheetLabel(null, true)).toBe("nie założony");
    expect(timesheetTone(null, true)).toBe("warning");
    expect(timesheetLabel(null, false)).toBe("bez obowiązku");
    expect(timesheetTone(null, false)).toBe("neutral");
    expect(timesheetLabel("submitted", true)).toBe("do akceptacji");
    expect(timesheetTone("submitted", true)).toBe("info");
    expect(timesheetLabel("approved", true)).toBe("zaakceptowany");
  });

  it("stan miesiąca na liście", () => {
    const base = {
      year: 2026,
      month: 9,
      label: "wrzesień 2026",
      people: 3,
      totals: {},
      pending_proposals: 0,
    };
    expect(monthState({ ...base, status: "closed", can_close: false }).label).toBe("zamknięty");
    expect(monthState({ ...base, status: "open", can_close: true }).label).toBe("do zamknięcia");
    expect(monthState({ ...base, status: "open", can_close: false }).label).toBe("w toku");
  });
});

describe("zapis stawki", () => {
  it("ostrzeżenie serwera (rok bez minimum, inna waluta) trafia do komunikatu jako informacja", () => {
    expect(rateToast({ warning: null })).toEqual(["Stawka zapisana", "success"]);
    expect(rateToast({ warning: "  " })).toEqual(["Stawka zapisana", "success"]);
    expect(rateToast({ warning: "Brak minimalnej stawki zlecenia na 2027 r." })).toEqual([
      "Stawka zapisana. Brak minimalnej stawki zlecenia na 2027 r.",
      "info",
    ]);
  });
});

describe("zamknięcie miesiąca: 409 z serwera", () => {
  it("czyta ostrzeżenia i liczbę propozycji", () => {
    const warnings = {
      response: {
        status: 409,
        data: {
          detail: {
            code: "close_warnings",
            message: "Przed zamknięciem sprawdź ostrzeżenia.",
            warnings: [{ code: "missing_rates", message: "1 os. ma godziny bez stawki", count: 1, people: [] }],
          },
        },
      },
    };
    expect(closeConflict(warnings)?.warnings).toHaveLength(1);
    const pending = {
      response: { status: 409, data: { detail: { code: "pending_bonuses", message: "x", count: 2 } } },
    };
    expect(closeConflict(pending)).toMatchObject({ code: "pending_bonuses", count: 2 });
    expect(closeConflict({ response: { status: 422, data: { detail: "zły miesiąc" } } })).toBeNull();
    expect(closeConflict({ response: { status: 409, data: { detail: "tekst" } } })).toBeNull();
  });
});

describe("Moje premie", () => {
  it("stawka i suma przyznanych w bieżącym roku per waluta", () => {
    const data: MyPayroll = {
      current_rate: {
        id: 1,
        user_id: 7,
        hourly_rate: "120.00",
        currency: "PLN",
        effective_from: "2026-09-01",
        effective_to: null,
        reason: null,
        set_by: 2,
      },
      rates: [],
      bonuses: [
        bonus({ amount: "1500.00" }),
        bonus({ id: 2, amount: "500.00" }),
        bonus({ id: 3, amount: "100.00", currency: "EUR" }),
        bonus({ id: 4, amount: "999.00", period_year: 2025 }),
        bonus({ id: 5, status: "proposed" }),
      ],
    };
    const stats = myStats(data, "2026-10-16");
    const value = (id: string) => nbsp(String(stats.find((s) => s.id === id)?.value));
    expect(value("rate")).toBe("120,00 zł/h");
    expect(value("bonuses")).toBe("2000,00 zł · 100,00 EUR");
    // „W drodze” = propozycje bez decyzji (+ prognozy), kwota jako szacunek.
    expect(stats.find((s) => s.id === "waiting")?.label).toBe("w drodze (1)");
    expect(value("waiting")).toBe("~ 772,80 zł");
    // Bez rozliczenia (np. awaria) nie ma liczby „wypłacone” — nie „0 zł”.
    expect(stats.some((s) => s.id === "paid")).toBe(false);
    const withSettlement = myStats(data, "2026-10-16", {
      year: 2026,
      months: [],
      bonuses_paid: { PLN: "1500.00" },
    });
    expect(nbsp(String(withSettlement.find((s) => s.id === "paid")?.value))).toBe("1500,00 zł");
    expect(withSettlement.find((s) => s.id === "bonuses")?.label).toBe("premie przyznane w 2026");

    // B2B i zlecenie: „wynagrodzenie dodatkowe”, nie „premie” (decyzja Artura 21.10.2026).
    const settled = { year: 2026, months: [], bonuses_paid: { PLN: "1500.00" } };
    for (const form of ["b2b", "zlecenie"] as const) {
      const words = myStats(data, "2026-10-16", settled, form);
      expect(words.find((s) => s.id === "bonuses")?.label).toBe(
        "wynagrodzenie dodatkowe przyznane w 2026",
      );
      expect(words.find((s) => s.id === "paid")?.label).toBe(
        "wynagrodzenie dodatkowe wypłacone w 2026",
      );
      expect(JSON.stringify(words)).not.toMatch(/premi/i);
    }
  });
});

describe("reguły premii — formularz", () => {
  const rules = {
    recruiter_tier_bounds: ["40", "50"] as [string, string],
    recruiter_tier_amounts: ["1000.00", "1500.00", "2000.00"] as [string, string, string],
    dl_percent: "10",
    monthly_hours: 168,
    eligible_business_days: 21,
    currency: "PLN" as const,
    extra_dl: [{ dl_user_id: 4, recipient_user_id: 5, dl_name: "A", recipient_name: "B" }],
    automation_since: null,
    league_types: ["quarterly_champions_dl"],
  };

  it("bez zmian daje te same wartości (bez nazw osób w treści)", () => {
    const result = rulesPayload(formFromRules(rules));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.payload).toMatchObject({
      recruiter_tier_bounds: ["40", "50"],
      recruiter_tier_amounts: ["1000", "1500", "2000"],
      dl_percent: "10",
      monthly_hours: 168,
      eligible_business_days: 21,
      automation_since: null,
      extra_dl: [{ dl_user_id: 4, recipient_user_id: 5 }],
    });
  });

  it("odrzuca odwrócone progi i zepsute liczby", () => {
    const form = formFromRules(rules);
    expect(rulesPayload({ ...form, boundLow: "60" }).ok).toBe(false);
    expect(rulesPayload({ ...form, tier2: "dużo" }).ok).toBe(false);
    expect(rulesPayload({ ...form, businessDays: "0" }).ok).toBe(false);
  });
});

describe("premia ręczna od przełożonego = propozycja dla Płac (19.10.2026)", () => {
  const manual = (overrides: Partial<BonusRow> = {}) =>
    bonus({ status: "proposed", source: "manual", proposed_by: 5, ...overrides });

  it("przełożony nie ma „Zatwierdź” przy swojej propozycji, tylko „Wycofaj”", () => {
    expect(bonusDecision(manual({ can_approve: false }), 5)).toEqual({
      approve: false,
      rejectLabel: "Wycofaj",
    });
  });

  it("Płace zatwierdzają propozycję ręczną i ją odrzucają", () => {
    expect(bonusDecision(manual({ can_approve: true }), 9)).toEqual({
      approve: true,
      rejectLabel: "Odrzuć",
    });
  });

  it("propozycja automatu bez flagi z serwera zostaje do zatwierdzenia", () => {
    expect(bonusDecision(bonus({ status: "proposed", source: "contract_placement" }), 5).approve).toBe(
      true,
    );
  });

  it("komunikat po dodaniu mówi, czy premia czeka na Płace", () => {
    expect(bonusCreatedToast(manual())).toBe("Premia czeka na zatwierdzenie Płac");
    expect(bonusCreatedToast(bonus({ status: "assigned", source: "manual" }))).toBe("Premia przyznana");
  });
});
