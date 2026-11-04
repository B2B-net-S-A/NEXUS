import { describe, expect, it } from "vitest";

import { manualFormError } from "@/components/hr/payroll/ksef/KsefDialogs";
import {
  canDetach,
  canFetch,
  invoiceStats,
  lastRunLine,
  maskNip,
  matchPerson,
  matchText,
  matchTone,
  runSummary,
  shortKsefNumber,
  shortName,
} from "@/components/hr/payroll/ksef/ksef-format";
import { STATUS, invoice } from "./ksef-fixtures";

describe("ksef-format", () => {
  it("names the match state after the settlement, or asks to assign", () => {
    expect(matchText(invoice())).toBe("rozbieżność");
    expect(matchTone(invoice())).toBe("warning");
    expect(matchText(invoice({ settlement: { ...invoice().settlement!, status: "ready" } }))).toBe(
      "zgodna",
    );
    expect(matchTone(invoice({ settlement: { ...invoice().settlement!, status: "ready" } }))).toBe(
      "success",
    );
    const unmatched = invoice({ match_status: "unmatched", settlement: null });
    expect(matchText(unmatched)).toBe("do przypisania");
    expect(matchTone(unmatched)).toBe("warning");
    expect(matchText(invoice({ match_status: "ignored", settlement: null }))).toBe("pominięta");
  });

  it("shows the person and month like the mockup", () => {
    expect(matchPerson(invoice())).toBe("Anna P. · październik");
    expect(matchPerson(invoice({ user: null, settlement: null }))).toBeNull();
    expect(shortName("Ola")).toBe("Ola");
  });

  it("shortens KSeF numbers and NIPs for narrow columns", () => {
    expect(shortKsefNumber("7777777777-20261105-0B91E4C2A7D8-1F")).toBe("…-20261105-0B91E4C2A7D8-1F");
    expect(shortKsefNumber(null)).toBe("—");
    expect(maskNip("1234563218")).toBe("123…3218");
  });

  it("counts invoices of the month and the hourly schedule", () => {
    const stats = invoiceStats(
      { invoices: [], counts: { total: 11, matched: 10, unmatched: 1, ignored: 0 } },
      "październik 2026",
      STATUS,
    );
    expect(stats.map((stat) => [stat.id, stat.value])).toEqual([
      ["total", 11],
      ["matched", 10],
      ["unmatched", 1],
      ["schedule", "co godzinę"],
    ]);
    const off = invoiceStats(
      { invoices: [], counts: { total: 0, matched: 0, unmatched: 0, ignored: 2 } },
      "październik 2026",
      { ...STATUS, enabled: false },
    );
    expect(off.map((stat) => stat.id)).toEqual(["total", "matched", "unmatched", "ignored"]);
  });

  it("summarises a run in one calm sentence", () => {
    expect(runSummary({ saved: 2, matched: 1, skipped: 5 })).toBe(
      "Nowe faktury od zespołu: 2 · dopasowane: 1 · 5 faktur dostawców pominięte.",
    );
    expect(runSummary({ saved: 0, pending: 1, partial: true })).toBe(
      "Brak nowych faktur od zespołu · w kolejce do ponownego pobrania: 1. Reszta w następnym pobraniu (limit KSeF).",
    );
  });

  it("describes the last run and blocks fetching during a KSeF pause", () => {
    expect(lastRunLine(STATUS)).toBe("Ostatnie pobranie: 17.11.2026, 14:00 (co godzinę)");
    expect(lastRunLine({ ...STATUS, last_run_at: null })).toBe("Jeszcze nie pobierano faktur.");
    expect(canFetch(STATUS)).toBe(true);
    expect(canFetch({ ...STATUS, blocked_until: "2026-11-17T13:15:00.000+00:00" })).toBe(false);
    expect(canFetch({ ...STATUS, enabled: false })).toBe(false);
    expect(canFetch(undefined)).toBe(false);
  });
});

describe("canDetach", () => {
  it("lets Payroll move or skip a matched invoice until the settlement is paid", () => {
    expect(canDetach(invoice())).toBe(true);
    expect(
      canDetach(
        invoice({
          settlement: { id: 3, status: "approved", expected_amount: "1.00", year: 2026, month: 10 },
        }),
      ),
    ).toBe(true);
    expect(
      canDetach(
        invoice({
          settlement: { id: 3, status: "paid", expected_amount: "1.00", year: 2026, month: 10 },
        }),
      ),
    ).toBe(false);
    expect(canDetach(invoice({ match_status: "unmatched", settlement: null }))).toBe(false);
    expect(canDetach(invoice({ match_status: "ignored", settlement: null }))).toBe(false);
  });
});

describe("manualFormError", () => {
  const form = {
    personId: "7",
    sellerNip: "",
    invoiceNumber: "R/1/10/2026",
    issueDate: "2026-11-03",
    saleDate: "",
    period: "2026-10",
    currency: "PLN" as const,
    net: "2400,00",
    vat: "0",
    gross: "2400",
  };
  const file = new File(["%PDF-1.4"], "faktura.pdf", { type: "application/pdf" });

  it("accepts a complete invoice", () => {
    expect(manualFormError(form, file)).toBeNull();
  });

  it.each([
    [{ personId: "" }, "Wybierz osobę."],
    [{ sellerNip: "1234563219" }, "NIP sprzedawcy ma złą sumę kontrolną."],
    [{ invoiceNumber: " " }, "Wpisz numer faktury."],
    [{ period: "" }, "Wybierz miesiąc rozliczenia."],
    [{ net: "12,345" }, "Kwoty wpisz jak 1234,50 (najwyżej dwa miejsca po przecinku)."],
    [{ gross: "2400,01" }, "Netto + VAT musi dać brutto co do grosza."],
    [{ vat: "600", gross: "3000" }, "VAT: najwyżej 23% netto (najwyższa stawka w Polsce)."],
  ])("refuses %o", (overrides, message) => {
    expect(manualFormError({ ...form, ...overrides }, file)).toBe(message);
  });

  it("needs the PDF", () => {
    expect(manualFormError(form, null)).toBe("Dołącz PDF faktury.");
  });
});
