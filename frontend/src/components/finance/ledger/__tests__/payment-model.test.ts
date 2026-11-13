import { describe, expect, it } from "vitest";

import {
  batchFormat,
  createBlocker,
  describeStatement,
  formatAccount,
  initialSelection,
  selectionSummary,
} from "@/components/finance/ledger/payment-model";
import type { PlanItem } from "@/lib/api/finance-payments";

function item(id: number, patch: Partial<PlanItem> = {}): PlanItem {
  return {
    entry_id: id,
    invoice_number: `FV/${id}/11/2026`,
    ksef_number: null,
    seller_name: "Dostawca Testowy",
    seller_nip: "1234563218",
    category: "office",
    due_date: "2026-11-12",
    currency: "PLN",
    gross_amount: "100.00",
    vat_amount: "18.70",
    to_pay: "100.00",
    amount_note: null,
    account_note: null,
    mode: "standard",
    mode_label: "Zwykły",
    mode_suggested: false,
    account: "90109000000000000000004242",
    account_source: "manual",
    account_source_label: "wpisany na karcie",
    title: `FV/${id}/11/2026`,
    white_list: { state: "listed", label: "W wykazie VAT", request_id: "r-1" },
    selectable: true,
    block: null,
    block_label: null,
    acks: [],
    hints: [],
    batch_id: null,
    preselect: true,
    ...patch,
  };
}

const ACK = { code: "white_list", label: "Rachunek spoza wykazu" };

describe("plan paczki", () => {
  it("domyślnie zaznacza tylko wiersze bez blokady i bez ostrzeżeń", () => {
    const items = [
      item(1),
      item(2, { acks: [ACK], preselect: false }),
      item(3, { selectable: false, block: "hold", preselect: false }),
    ];
    expect([...initialSelection(items)]).toEqual([1]);
  });

  it("ostrzeżenie bez odhaczenia blokuje paczkę, odhaczone ją odblokowuje", () => {
    const items = [item(1), item(2, { acks: [ACK], to_pay: "20000.00" })];
    const pending = selectionSummary(items, new Set([1, 2]), new Set());
    expect(pending.missingAcks).toEqual([2]);
    expect(pending.canCreate).toBe(false);
    expect(createBlocker(pending)).toBe("Odhacz ostrzeżenia przy 1 fakturze.");
    const done = selectionSummary(items, new Set([1, 2]), new Set([2]));
    expect(done.canCreate).toBe(true);
    expect(done.totals).toEqual({ PLN: 20100 });
    expect(createBlocker(done)).toBeNull();
  });

  it("zablokowany wiersz nie liczy się do sumy, nawet zaznaczony", () => {
    const items = [item(1), item(2, { selectable: false, block: "paid" })];
    const summary = selectionSummary(items, new Set([1, 2]), new Set());
    expect(summary.count).toBe(1);
    expect(summary.totals).toEqual({ PLN: 100 });
  });

  it("dwie waluty w jednej paczce — nie", () => {
    const items = [item(1), item(2, { currency: "EUR", to_pay: "50.00" })];
    const summary = selectionSummary(items, new Set([1, 2]), new Set());
    expect(summary.mixed).toBe(true);
    expect(summary.canCreate).toBe(false);
    expect(createBlocker(summary)).toMatch(/jedna waluta/);
    expect(createBlocker(selectionSummary(items, new Set(), new Set()))).toBe(
      "Zaznacz faktury do paczki.",
    );
  });

  it("Elixir tylko w złotych", () => {
    expect(batchFormat("PLN", "elixir")).toBe("elixir");
    expect(batchFormat("EUR", "elixir")).toBe("csv");
    expect(batchFormat(null, "csv")).toBe("csv");
  });
});

describe("wyciąg i rachunek", () => {
  it("opis wyniku wyciągu pomija zera", () => {
    expect(
      describeStatement({
        format: "mt940",
        statement: "abc",
        operations: 9,
        debits: 7,
        matched: 3,
        partial: 1,
        unmatched: 0,
        duplicates: 0,
        known: 0,
        team: 2,
        skipped: 1,
      }),
    ).toBe("Zapłacone: 3, częściowo: 1, zespół (Płace): 2. Obciążeń w pliku: 7.");
  });

  it("rachunek krajowy w grupach z PL, zagraniczny bez zmian", () => {
    expect(formatAccount("90109000000000000000004242")).toBe(
      "PL90 1090 0000 0000 0000 0000 4242",
    );
    expect(formatAccount("DE89370400440532013000")).toBe("DE89 3704 0044 0532 0130 00");
    expect(formatAccount(null)).toBe("—");
  });
});
