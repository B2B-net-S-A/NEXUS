/**
 * Rozliczenia (etap 4) — czyste funkcje panelu osoby i kolejki Płac.
 * Dane fikcyjne; NIP-y z poprawną sumą kontrolną liczone w teście.
 */
import { describe, expect, it } from "vitest";

import type { MySettlementMonth, MySettlements, SettlementRow } from "@/lib/api/hr-settlements";

import {
  accountLabel,
  copyItemsText,
  formatNip,
  mergeSettlementYears,
  needsMyAction,
  nextStepText,
  nipValid,
  previousMonthLine,
  queueStatus,
  settlementLayout,
  showsPreviousYear,
  stepDetail,
  stepLabel,
} from "../settlement-format";

function month(overrides: Partial<MySettlementMonth> = {}): MySettlementMonth {
  return {
    settlement_id: 1,
    year: 2026,
    month: 10,
    label: "październik 2026",
    employment_type: "b2b",
    currency: "PLN",
    final: true,
    status: "awaiting_document",
    status_label: "Czeka na fakturę",
    amount: "17160.00",
    amount_basis: "net",
    hours: "168.00",
    hourly_rate: "95.00",
    hours_confirmed: true,
    items: [
      { kind: "hours", label: "Usługi · 160 h × 95,00", amount: "15200.00", hours: "160", rate: "95", days: null, bonus_id: null },
      { kind: "bonus", label: "Premia · Rekruter", amount: "1960.00", hours: null, rate: null, days: null, bonus_id: 7 },
    ],
    steps: [],
    invoice: null,
    account_last4: "4521",
    account_source: "white_list",
    due_on: "2026-11-18",
    paid_on: null,
    correction_requested_at: null,
    discrepancy: null,
    has_pdf: false,
    ...overrides,
  };
}

function nipWithChecksum(body: string): string {
  const weights = [6, 5, 7, 2, 3, 4, 5, 6, 7];
  const check = weights.reduce((sum, w, i) => sum + w * Number(body[i]), 0) % 11;
  return body + String(check);
}

describe("settlement-format", () => {
  it("kopiuje pozycje z tabulatorem i sumą netto (R2)", () => {
    const text = copyItemsText(month());
    const lines = text.split("\n");
    expect(lines).toHaveLength(3);
    expect(lines[0]).toMatch(/^Usługi · 160 h × 95,00\t15\s200,00\szł$/);
    expect(lines[2]).toMatch(/^Razem netto\t17\s160,00\szł$/);
    expect(copyItemsText(month({ amount_basis: "gross" }))).toContain("Razem brutto");
  });

  it("krok terminu i wypłaty mówi „do dnia”, póki nie jest zrobiony", () => {
    const due = { key: "due", label: "Do zapłaty", state: "current" as const, date: "2026-11-18", detail: "14 dni od numeru KSeF" };
    expect(stepLabel(due)).toBe("Do zapłaty do 18.11");
    expect(stepDetail(due)).toBe("14 dni od numeru KSeF");
    const done = { key: "hours", label: "Raport potwierdzony", state: "done" as const, date: "2026-11-03", detail: "Marta Fikcyjna" };
    expect(stepLabel(done)).toBe("Raport potwierdzony");
    expect(stepDetail(done)).toBe("03.11 · Marta Fikcyjna");
  });

  it("„co dalej” według stanu i formy", () => {
    expect(nextStepText(month())).toMatch(/Wystaw fakturę/);
    expect(nextStepText(month({ status: "mismatch", correction_requested_at: "2026-11-06T10:00:00+01:00" }))).toMatch(
      /poprosiły o korektę 06\.11/,
    );
    expect(nextStepText(month({ status: "paid", paid_on: "2026-11-14" }))).toBe("Opłacono 14.11.");
    expect(nextStepText(month({ status: "paid", paid_on: "2026-11-10", employment_type: "zlecenie" }))).toBe(
      "Wypłacono 10.11.",
    );
    expect(nextStepText(month({ status: "estimate", hours_confirmed: false, final: false }))).toMatch(
      /po potwierdzeniu raportu godzin/,
    );
  });

  it("premie przy UoP, „wynagrodzenie dodatkowe” przy B2B i zleceniu (21.10.2026)", () => {
    const estimate = { status: "estimate" as const, hours_confirmed: true, final: false };
    expect(nextStepText(month({ ...estimate, employment_type: "uop" }))).toMatch(/gdy dojdą premie\.$/);
    expect(nextStepText(month(estimate))).toMatch(/gdy dojdzie wynagrodzenie dodatkowe\.$/);
    expect(previousMonthLine(month({ employment_type: "zlecenie" }))).toMatch(
      /w tym wynagrodzenie dodatkowe 1\s?960,00\s?zł$/,
    );
    expect(previousMonthLine(month({ employment_type: "uop" }))).toMatch(/w tym premie/);
  });

  it("NIP: suma kontrolna, zapis z kreskami, zły NIP odrzucony", () => {
    const nip = nipWithChecksum("123456321");
    expect(nipValid(nip)).toBe(true);
    expect(nipValid(`PL ${nip.slice(0, 3)}-${nip.slice(3)}`)).toBe(true);
    const wrong = nip.slice(0, 9) + String((Number(nip[9]) + 1) % 10);
    expect(nipValid(wrong)).toBe(false);
    expect(nipValid("12345")).toBe(false);
    expect(formatNip(nip)).toBe(`${nip.slice(0, 3)}-${nip.slice(3, 6)}-${nip.slice(6, 8)}-${nip.slice(8)}`);
  });

  it("rachunek tylko z 4 ostatnimi cyframi i źródłem", () => {
    expect(accountLabel("4521", "white_list")).toBe("•• 4521 · z białej listy VAT");
    expect(accountLabel("0937", "manual")).toBe("•• 0937 · wpisany ręcznie");
    expect(accountLabel(null, null)).toBe("brak rachunku");
  });

  it("stan kolejki: różnica ze znakiem, rachunek spoza listy, godziny niepotwierdzone", () => {
    const base = {
      status: "mismatch",
      status_label: "Rozbieżność",
      discrepancy: "120.00",
      currency: "PLN",
      problems: ["amount"],
      employment_type: "b2b",
      hours_confirmed: true,
      paid_on: null,
    } as unknown as SettlementRow;
    expect(queueStatus(base)).toBe("rozbieżność +120,00");
    expect(queueStatus({ ...base, discrepancy: "-0.01" })).toBe("rozbieżność −0,01");
    expect(queueStatus({ ...base, discrepancy: "0.00", problems: ["white_list"] })).toBe(
      "rachunek spoza białej listy",
    );
    expect(queueStatus({ ...base, discrepancy: "0.00", problems: ["gross", "white_list"] })).toBe(
      "brutto albo VAT do sprawdzenia",
    );
    // Inny wystawca faktury wygrywa z różnicą kwoty — to nie różnica do uznania.
    expect(queueStatus({ ...base, problems: ["amount", "seller"] })).toBe(
      "NIP wystawcy faktury inny niż w danych do rozliczeń",
    );
    expect(
      queueStatus({
        ...base,
        status: "ready",
        status_label: "Kwota policzona",
        employment_type: "zlecenie",
        hours_confirmed: false,
      }),
    ).toBe("godziny niepotwierdzone");
    expect(queueStatus({ ...base, status: "paid", status_label: "Opłacono", paid_on: "2026-11-15" })).toBe(
      "opłacono 15.11",
    );
  });
});

describe("układ „Mój czas → Rozliczenie” (audyt A2, 19.10.2026)", () => {
  const at = (y: number, m: number, extra: Partial<MySettlementMonth> = {}) =>
    month({ year: y, month: m, label: `${m}/${y}`, ...extra });
  const year = (y: number, months: MySettlementMonth[]): MySettlements => ({
    year: y,
    employment_type: "b2b",
    settlement_word: "Faktura",
    account_last4: null,
    account_source: null,
    nip: null,
    months,
  });

  it("działanie osoby: czeka na fakturę albo Płace poprosiły o korektę", () => {
    expect(needsMyAction(month({ status: "awaiting_document" }))).toBe(true);
    expect(needsMyAction(month({ status: "mismatch", correction_requested_at: "2026-11-05" }))).toBe(true);
    expect(needsMyAction(month({ status: "mismatch", correction_requested_at: null }))).toBe(false);
    expect(needsMyAction(month({ status: "estimate" }))).toBe(false);
    expect(needsMyAction(month({ status: "paid" }))).toBe(false);
  });

  it("na górze miesiąc do działania, potem bieżący szacunek; reszta w poprzednich", () => {
    const estimate = at(2026, 11, { status: "estimate", final: false, settlement_id: null });
    const awaiting = at(2026, 10, { status: "awaiting_document" });
    const paid = at(2026, 9, { status: "paid" });
    const layout = settlementLayout([estimate, awaiting, paid]);
    expect(layout.featured.map((group) => group[0].month)).toEqual([10, 11]);
    expect(layout.previous.map((entry) => entry.month)).toEqual([9]);
  });

  it("bez miesiąca do działania na górze zostaje najnowszy", () => {
    const layout = settlementLayout([at(2026, 10, { status: "approved" }), at(2026, 9, { status: "paid" })]);
    expect(layout.featured.map((group) => group[0].month)).toEqual([10]);
    expect(layout.previous.map((entry) => entry.month)).toEqual([9]);
  });

  it("wszystkie waluty miesiąca razem — PLN nie spada do poprzednich", () => {
    const eur = at(2026, 10, { currency: "EUR", status: "approved" });
    const pln = at(2026, 10, { currency: "PLN", status: "approved" });
    const layout = settlementLayout([eur, pln, at(2026, 9, { status: "paid" })]);
    expect(layout.featured).toHaveLength(1);
    expect(layout.featured[0].map((entry) => entry.currency)).toEqual(["EUR", "PLN"]);
    expect(layout.previous.map((entry) => entry.month)).toEqual([9]);
  });

  it("poprzedni rok: w styczniu cały, potem tylko miesiące do działania", () => {
    expect(showsPreviousYear("2027-01-05")).toBe(true);
    expect(showsPreviousYear("2027-02-01")).toBe(false);
    const december = at(2026, 12, { status: "awaiting_document" });
    const november = at(2026, 11, { status: "paid" });
    const last = year(2026, [december, november]);
    const january = mergeSettlementYears(year(2027, []), last, "2027-01-05");
    expect(january.year).toBe(2027);
    expect(january.months.map((entry) => entry.month)).toEqual([12, 11]);
    const march = mergeSettlementYears(year(2027, [at(2027, 3, { status: "estimate" })]), last, "2027-03-02");
    expect(march.months.map((entry) => `${entry.year}-${entry.month}`)).toEqual(["2027-3", "2026-12"]);
    expect(mergeSettlementYears(year(2027, []), undefined, "2027-01-05").months).toEqual([]);
  });
});
