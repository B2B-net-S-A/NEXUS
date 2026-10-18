import { describe, expect, it } from "vitest";

import {
  canAcceptDifference,
  canMarkPaid,
  checkText,
  defaultPeriod,
  looseInvoices,
  paymentText,
  paymentTone,
  quantityText,
  rowInvoiceText,
  rowStatusNote,
  summaryStats,
  targetsText,
  totalsText,
} from "@/components/clients/invoicing/invoicing-format";
import { statusSummary } from "@/components/clients/invoicing/FinanceSalesInvoicesTab";

import { CLIENT_MONTH, invoice, row } from "@/app/preview/client-invoicing/fixtures";

const nbsp = (text: string) => text.replace(/ /g, " ");

describe("invoicing-format", () => {
  it("defaults to the previous month, also across the year boundary", () => {
    expect(defaultPeriod("2026-11-03")).toBe("2026-10");
    expect(defaultPeriod("2027-01-05")).toBe("2026-12");
  });

  it("explains a position as quantity × unit price", () => {
    const [md] = row().lines;
    expect(nbsp(quantityText(md) ?? "")).toBe("21 MD × 1200,00 zł");
    const waiting = { ...md, quantity: null };
    expect(quantityText(waiting)).toBeNull();
    const month = { ...md, basis: "month" as const, unit: "mies.", quantity: "1", unit_price: "21000" };
    expect(nbsp(quantityText(month) ?? "")).toBe("miesiąc × 21 000,00 zł");
  });

  it("shows payment state with overdue first", () => {
    expect(nbsp(paymentText(invoice()))).toBe("zapłacono 14.11");
    expect(paymentTone(invoice())).toBe("success");
    const late = invoice({ payment_status: "partial", overdue_days: 10, to_pay: "100.00" });
    expect(paymentText(late)).toBe("po terminie 10 dni · zapłacono część");
    expect(paymentTone(late)).toBe("danger");
    const open = invoice({ payment_status: "unpaid", overdue_days: 0, paid_on: null });
    expect(paymentText(open)).toBe("termin 17.11");
    expect(paymentText(invoice({ payment_status: "unpaid", overdue_days: 1 }))).toBe(
      "po terminie 1 dzień",
    );
  });

  it("names differences with a sign and status of rows", () => {
    const diff = invoice({ check: "difference", difference: "75.00" });
    expect(nbsp(checkText(diff))).toBe("różnica +75,00 zł");
    const [, , withDiff, notInvoiced] = CLIENT_MONTH.rows;
    expect(nbsp(rowStatusNote(withDiff) ?? "")).toBe("różnica do sprawdzenia · +75,00 zł");
    expect(rowInvoiceText(notInvoiced, [])).toBe("jeszcze nie wystawiona");
    const sheet = row({ status: "sheet", status_label: "wg arkusza Finansów", sheet_invoiced: "11000" });
    expect(nbsp(rowInvoiceText(sheet, []))).toBe("wg arkusza Finansów: 11 000,00 zł");
  });

  it("lists invoices not attached to any row and what they wait for", () => {
    const loose = looseInvoices(CLIENT_MONTH.rows, CLIENT_MONTH.invoices);
    expect(loose.map((item) => item.invoice_number)).toEqual(["FS 10/9/2026"]);
    expect(targetsText(loose[0])).toContain("kwota nie pasuje");
    expect(targetsText(invoice())).toBe("ZAM/2026/118");
  });

  it("allows decisions only where they make sense", () => {
    expect(canAcceptDifference(invoice({ check: "difference" }))).toBe(true);
    expect(canAcceptDifference(invoice({ check: "difference", invoice_kind: "correction" }))).toBe(
      false,
    );
    expect(canAcceptDifference(invoice())).toBe(false);
    expect(canMarkPaid(invoice())).toBe(false);
    expect(canMarkPaid(invoice({ to_pay: "10.00" }))).toBe(true);
  });

  it("builds compact stats and totals per currency", () => {
    expect(nbsp(totalsText([{ currency: "PLN", amount: "79545.00" }, { currency: "EUR", amount: "100" }]))).toBe(
      "79 545,00 zł · 100,00 EUR",
    );
    const stats = summaryStats(CLIENT_MONTH.summary, "2026-10", 2);
    expect(stats.map((stat) => stat.id)).toEqual(["rows", "invoiced", "expected", "differences", "overdue"]);
    expect(statusSummary({ ok: 2, not_invoiced: 1, difference: 0 })).toBe("zgodne: 2 · bez faktury: 1");
  });
});
