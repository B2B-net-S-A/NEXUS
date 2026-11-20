import { describe, expect, it } from "vitest";

import {
  frontierStep,
  invoiceStep,
  ksefStep,
  monthSteps,
  paymentClass,
  paymentStep,
  rcpStep,
  type MonthStep,
  type RcpInput,
} from "@/components/clients/invoicing/month-steps";
import type { ClientInvoicing, InvoicingSummary } from "@/lib/api/client-invoicing";

import { CLIENT_MONTH, invoice, row } from "@/app/preview/client-invoicing/fixtures";

const nbsp = (text: string | null) => (text ?? "").replace(/[\u00a0\u202f]/g, " ");

const SUMMARY: InvoicingSummary = {
  rows: 2,
  not_invoiced: 0,
  invoiced: 2,
  differences: 0,
  unknown: 0,
  cost: 0,
  unmatched_invoices: 0,
  expected: [{ currency: "PLN", amount: "57120.00" }],
  invoiced_net: [{ currency: "PLN", amount: "57120.00" }],
};

function month(overrides: Partial<ClientInvoicing> = {}): ClientInvoicing {
  return {
    ...CLIENT_MONTH,
    rows: [row(), row({ key: "o21", group_id: null, order_id: 21, invoice_ids: [2] })],
    invoices: [invoice(), invoice({ id: 2 })],
    summary: SUMMARY,
    ...overrides,
  };
}

const READY = (kinds: ("actual" | "estimate" | null)[]): RcpInput => ({
  state: "ready",
  rows: kinds.map((kind) => ({ kind })),
});

/** Żaden krok nie mówi „niezapłacona” — brak danych to brak danych. */
function expectNoUnpaidClaim(steps: MonthStep[]) {
  for (const step of steps) {
    expect(`${step.value} ${step.note ?? ""}`).not.toMatch(/niezapłac|nie zapłac/i);
  }
}

describe("rcpStep", () => {
  it("bez przyjętego RCP mówi „brak w NEXUSIE”, nie „czeka”", () => {
    const step = rcpStep(READY([null, null, null]));
    expect(step.value).toBe("brak w NEXUSIE");
    expect(step.note).toBe("0 z 3 osób z przyjętym RCP");
    expect(step.done).toBe(false);
    expect(step.started).toBe(false);
    expect(`${step.value} ${step.note}`).not.toMatch(/czeka/);
  });

  it("liczy przyjęte RCP, także z planu", () => {
    const part = rcpStep(READY(["actual", null, "estimate"]));
    expect(part.value).toBe("2 z 3 przyjętych");
    expect(part.note).toBe("1 bez przyjętego RCP · 1 z planu");
    expect(part.done).toBe(false);
    expect(part.started).toBe(true);
    const all = rcpStep(READY(["actual", "actual"]));
    expect(all.value).toBe("2 z 2 przyjętych");
    expect(all.tone).toBe("success");
    expect(all.done).toBe(true);
  });

  it("moduł zamknięty, brak dostępu albo awaria to nie „0 przyjętych” — i nie wyglądają tak samo", () => {
    expect(rcpStep({ state: "unavailable" })).toMatchObject({ value: "bez dostępu", note: "rozliczenia RCP są poza Twoim dostępem" });
    expect(rcpStep({ state: "error" })).toMatchObject({ value: "nie udało się wczytać", note: null });
    expect(rcpStep({ state: "loading" }).value).toBe("…");
    expect(rcpStep(READY([])).note).toBeNull();
  });
});

describe("invoiceStep i ksefStep", () => {
  it("do faktury: kwota, zamówienia i to, czego nie da się policzyć", () => {
    const step = invoiceStep(month({ summary: { ...SUMMARY, unknown: 1, cost: 1 } }));
    expect(nbsp(step.value)).toBe("57 120,00 zł");
    expect(step.note).toBe("2 zamówienia · 1 czeka na zużycie MD · 1 kosztowe bez kwoty");
    expect(step.tone).toBe("warning");
    expect(step.done).toBe(false);
  });

  it("bez „Wyników firmy” zamiast kwoty liczba zamówień", () => {
    const step = invoiceStep(month({ summary: { ...SUMMARY, totals_hidden: true } }));
    expect(step.value).toBe("2 zamówienia");
    expect(step.note).toBeNull();
    expect(step.done).toBe(true);
  });

  it("faktura bez KSeF: zamówienia bez faktury, krok nie jest skończony", () => {
    const step = ksefStep(month({ summary: { ...SUMMARY, invoiced: 0, not_invoiced: 2 } }));
    expect(step.value).toBe("0 z 2 zamówień");
    expect(step.started).toBe(false);
    expect(step.done).toBe(false);
    expect(step.tone).toBe("neutral");
  });

  it("KSeF: różnice i faktury do przypisania w drobnym druku", () => {
    const step = ksefStep(month({ summary: { ...SUMMARY, differences: 1, unmatched_invoices: 2 } }));
    expect(step.value).toBe("2 z 2 zamówień");
    expect(step.note).toBe("1 różnica do sprawdzenia · 2 faktury do przypisania");
    expect(step.tone).toBe("warning");
    expect(step.done).toBe(false);
    const done = ksefStep(month());
    expect(done.done).toBe(true);
    expect(done.note).toBe("każde zamówienie ma fakturę");
  });
});

describe("paymentStep — tylko to, co potwierdzają dane", () => {
  it("bez faktur nie ma czego płacić", () => {
    const step = paymentStep(month({ invoices: [] }));
    expect(step.value).toBe("nie ma faktur");
    expect(step.started).toBe(false);
  });

  it("zapłacone tylko z zapisaną zapłatą", () => {
    const step = paymentStep(month());
    expect(step).toMatchObject({ value: "zapłacone", note: "2 faktury zapłacone", tone: "success", done: true });
  });

  it("przed terminem z najbliższym terminem", () => {
    const step = paymentStep(
      month({
        invoices: [
          invoice({ payment_status: "unpaid", paid: "0.00", paid_on: null, due_date: "2026-12-07" }),
          invoice({ id: 2, payment_status: "unpaid", paid: "0.00", paid_on: null, due_date: "2026-11-24" }),
        ],
      }),
    );
    expect(step.value).toBe("przed terminem");
    expect(step.note).toBe("najbliższy termin 24.11");
    expect(step.done).toBe(false);
  });

  it("KSeF bez potwierdzonej zapłaty: „brak danych o zapłacie”, nigdy „niezapłacona”", () => {
    const unknown = invoice({
      payment_status: "unpaid",
      paid: "0.00",
      paid_on: null,
      payment_unknown: true,
      payment_unknown_reason: "account_outside_ledger",
      payment_account: "9022",
    });
    const step = paymentStep(month({ invoices: [unknown, { ...unknown, id: 2 }] }));
    expect(step.value).toBe("brak danych o zapłacie");
    expect(step.note).toBe("rachunek …9022 poza Księgą");
    expect(step.tone).toBe("neutral");
    expectNoUnpaidClaim([step]);
  });

  it("brak wyciągów: powód z dniem, do którego wyciągi są ciągłe", () => {
    const base = { payment_status: "unpaid" as const, paid: "0.00", paid_on: null, payment_unknown: true };
    const step = paymentStep(
      month({
        invoices: [
          invoice({ ...base, payment_unknown_reason: "statements", payment_account: "8025", statements_until: "2026-11-12" }),
          invoice({ ...base, id: 2, payment_unknown_reason: "statements", payment_account: "8025", statements_until: null }),
        ],
      }),
    );
    expect(step.value).toBe("brak danych o zapłacie");
    // Dwa różne powody — zdanie ogólne zamiast jednego z nich.
    expect(step.note).toBe("termin minął, a wyciągi rachunku tego nie rozstrzygają");
  });

  it("część zapłacona, reszta bez danych — bez zgadywania", () => {
    const step = paymentStep(
      month({
        invoices: [
          invoice(),
          invoice({ id: 2, payment_status: "unpaid", paid: "0.00", paid_on: null, payment_unknown: true }),
          invoice({ id: 3, payment_status: "unpaid", paid: "0.00", paid_on: null, due_date: "2026-12-01" }),
        ],
      }),
    );
    expect(step.value).toBe("1 z 3 zapłacone");
    expect(step.note).toBe("1 bez danych o zapłacie · 1 przed terminem");
    expectNoUnpaidClaim([step]);
  });

  it("„po terminie” tylko z dowodem z wyciągów i tylko, gdy wolno je pokazać", () => {
    const late = invoice({ id: 2, payment_status: "unpaid", paid: "0.00", paid_on: null, overdue_days: 6, statements_until: "2026-11-30" });
    const open = invoice({ id: 3, payment_status: "unpaid", paid: "0.00", paid_on: null, due_date: "2026-12-10" });
    const shown = paymentStep(month({ invoices: [late, open] }));
    expect(shown.value).toBe("1 z 2 po terminie");
    expect(shown.note).toBe("1 przed terminem");
    expect(shown.tone).toBe("danger");
    const hidden = paymentStep(month({ invoices: [late, open] }), { showOverdue: false });
    expect(hidden.value).toBe("1 z 2 przed terminem");
    // Karta w Przeglądzie ma ok. 150 px na stan: krótsza wersja bez „z 2”.
    expect(hidden.short).toBe("1 przed terminem");
    expect(hidden.note).toBe("1 bez danych o zapłacie");
    expect(hidden.tone).toBe("neutral");
  });

  it("wpłata części z wyciągu zostaje faktem, choć o reszcie NEXUS nie wie", () => {
    const partial = invoice({ payment_status: "partial", paid: "100.00", to_pay: "900.00", paid_on: "2026-11-12", payment_unknown: true });
    expect(paymentClass(partial)).toBe("partial");
    const step = paymentStep(
      month({ invoices: [partial, invoice({ id: 2, payment_status: "unpaid", paid: "0.00", paid_on: null, payment_unknown: true })] }),
    );
    expect(step.value).toBe("1 z 2 zapłacone w części");
    expect(step.short).toBe("1 z 2 w części");
    expect(step.note).toBe("1 bez danych o zapłacie");
    expectNoUnpaidClaim([step]);
  });

  it("pomija faktury pominięte przez Finanse i te bez kwoty do zapłaty", () => {
    expect(paymentClass(invoice({ payment_status: "none" }))).toBe("nothing");
    const step = paymentStep(
      month({ invoices: [invoice(), invoice({ id: 2, match_status: "ignored", payment_status: "unpaid" }), invoice({ id: 3, payment_status: "none" })] }),
    );
    expect(step.value).toBe("zapłacone");
    expect(step.note).toBe("1 faktura zapłacona");
  });
});

describe("monthSteps i frontierStep", () => {
  it("miesiąc bez zamówień i faktur nie ma kroków", () => {
    expect(monthSteps(month({ rows: [], invoices: [] }), READY([]))).toEqual([]);
  });

  it("cztery kroki w kolejności RCP → do faktury → KSeF → zapłata", () => {
    const steps = monthSteps(month(), READY([null, null]));
    expect(steps.map((step) => step.label)).toEqual(["RCP", "Do faktury", "W KSeF", "Zapłata"]);
    expectNoUnpaidClaim(steps);
  });

  it("RCP spoza NEXUSA nie zatrzymuje miesiąca na pierwszym kroku", () => {
    const unpaid = { payment_status: "unpaid" as const, paid: "0.00", paid_on: null, due_date: "2026-12-07" };
    const steps = monthSteps(month({ invoices: [invoice(unpaid), invoice({ ...unpaid, id: 2 })] }), READY([null, null]));
    expect(frontierStep(steps)?.key).toBe("payment");
    const noInvoices = monthSteps(
      month({ invoices: [], summary: { ...SUMMARY, invoiced: 0, not_invoiced: 2 } }),
      READY([null, null]),
    );
    expect(frontierStep(noInvoices)?.key).toBe("ksef");
    expect(frontierStep([])).toBeNull();
  });

  it("po skończonym kroku miesiąc stoi na następnym", () => {
    const steps = monthSteps(
      month({ invoices: [], summary: { ...SUMMARY, invoiced: 0, not_invoiced: 2 } }),
      READY(["actual", "actual"]),
    );
    // RCP przyjęte, kwota policzona, KSeF jeszcze nic — miesiąc stoi na KSeF.
    expect(frontierStep(steps)?.key).toBe("ksef");
  });
});
