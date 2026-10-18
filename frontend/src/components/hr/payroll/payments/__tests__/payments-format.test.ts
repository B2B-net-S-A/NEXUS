import { describe, expect, it } from "vitest";

import type { FinanceList, StatementImport } from "@/lib/api/hr-payments";

import {
  accountLabel,
  amountToPay,
  batchStatus,
  documentLabel,
  financeStats,
  statementFileProblem,
  statementSummary,
  symfoniaFileLabel,
} from "../payments-format";
import { payableRow } from "./payments-fixtures";

const mandate = payableRow({
  settlement_id: 2,
  name: "Kuba Lato",
  employment_type: "zlecenie",
  form_label: "Zlecenie",
  amount_basis: "gross",
  amount_to_pay: null,
  expected_amount: "1856.00",
  invoices: [],
  title: "Wynagrodzenie zlecenie 10/2026",
  account_source: "manual",
  account_last4: "0937",
});

describe("Przelewy — słowa i liczby", () => {
  it("B2B płaci brutto faktury, zlecenie — netto z programu płacowego", () => {
    expect(amountToPay(payableRow())).toMatch(/21\s106,80\szł/);
    expect(amountToPay(mandate)).toBe("netto z programu płacowego");
    expect(documentLabel(mandate)).toBe("potwierdzenie godzin");
    expect(documentLabel(payableRow({ employment_type: "uop", invoices: [] }))).toBe("lista płac");
  });

  it("rachunek: tylko 4 cyfry i źródło; brak = czerwony, uznany spoza listy = ostrzeżenie", () => {
    expect(accountLabel(payableRow())).toEqual({ text: "•• 4521 · biała lista VAT", tone: "success" });
    expect(accountLabel(mandate).text).toBe("•• 0937 · wpisany przez Kadry");
    expect(accountLabel(payableRow({ account_last4: null })).tone).toBe("danger");
    expect(accountLabel(payableRow({ white_list_override: true })).tone).toBe("warning");
  });

  it("liczby nad listą: zatwierdzone, faktury, program płacowy, po terminie, do decyzji", () => {
    const data: FinanceList = {
      year: 2026,
      month: 10,
      rows: [payableRow(), mandate],
      totals_to_pay: { PLN: "21106.80" },
      stats: { payable: 2, b2b: 1, payroll_program: 1, overdue: 0, unmatched_lines: 3 },
      transfer_batch_enabled: false,
    };
    const stats = financeStats(data);
    expect(stats.map((s) => s.value)).toEqual([2, 1, 1, 0, 3]);
    expect(stats[1].title).toMatch(/21\s106,80\szł/);
  });

  it("wynik wyciągu w jednym zdaniu; ten sam plik drugi raz mówi to wprost", () => {
    const result: StatementImport = {
      format: "mt940",
      statement: "abc",
      already_imported: false,
      operations: 5,
      debits: 4,
      matched: 2,
      already_paid: 0,
      unmatched: 1,
      duplicates: 0,
      skipped: 2,
      accounts_unreadable: false,
      paid: [],
      warnings: [],
    };
    expect(statementSummary(result)).toBe(
      "Rozpoznane: 2 przelewów → „opłacono”. Do decyzji: 1. Pominięte (nie dotyczą zespołu): 2.",
    );
    expect(statementSummary({ ...result, already_imported: true })).toMatch(/był już wgrany/);
  });

  it("plik wyciągu sprawdzony przed wysłaniem (pusty, za duży, zły format)", () => {
    const file = (name: string, size: number) =>
      new File([new Uint8Array(size)], name, { type: "application/octet-stream" });
    expect(statementFileProblem(file("wyciag.sta", 10))).toBeNull();
    expect(statementFileProblem(file("wyciag.XML", 10))).toBeNull();
    expect(statementFileProblem(file("wyciag.sta", 0))).toBe("Plik jest pusty.");
    expect(statementFileProblem(file("wyciag.pdf", 10))).toMatch(/MT940/);
    expect(statementFileProblem(file("wyciag.sta", 5 * 1024 * 1024 + 1))).toMatch(/5 MB/);
  });

  it("stan paczki przelewów i nazwy plików Symfonii", () => {
    const batch = {
      batch_key: "k",
      format: "elixir" as const,
      created_at: null,
      execution_date: "2026-11-18",
      count: 3,
      active: 3,
      paid: 1,
      total: "100.00",
      created_by_name: null,
      status: "created" as const,
    };
    expect(batchStatus(batch).text).toBe("opłacono 1 z 3");
    expect(batchStatus({ ...batch, paid: 0 }).text).toBe("czeka na wysłanie");
    expect(batchStatus({ ...batch, status: "cancelled" }).text).toBe("anulowana");
    expect(symfoniaFileLabel("zdarzenia_2026-09.xml")).toBe("Nieobecności i nadgodziny (XML)");
    expect(symfoniaFileLabel("zestawienie_2026-09.pdf")).toMatch(/PDF/);
  });
});
