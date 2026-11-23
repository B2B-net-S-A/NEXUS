import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MonthCloseClient, SettlementRow } from "@/lib/api/client-settlements";

import { ClientMonthStrip, monthSteps, topReasons } from "../ClientMonthStrip";
import { reserveCsv } from "../ClosingPanel";
import { clientInvoiceState, issueHref, reminderNote, settlementsHref } from "../MonthCloseView";
import { reasonPlan } from "../reason-plan";

function row(over: Partial<SettlementRow>): SettlementRow {
  return {
    contract_id: 1,
    settlement_id: 1,
    person: "Osoba Testowa",
    order_number: null,
    status: "ok",
    issues: null,
    md_regular: "20.000",
    md_extra: null,
    md_charged: "20.000",
    md_remaining_after: null,
    amount_cost: null,
    amount_revenue: null,
    integration_cost: null,
    margin: null,
    margin_pct: null,
    contractor_invoice: "none",
    client_invoice: "waiting",
    ...over,
  } as SettlementRow;
}

function client(over: Partial<MonthCloseClient>): MonthCloseClient {
  return {
    client_id: 7,
    name: "Klient",
    people: 10,
    clean: 0,
    accepted: 0,
    decide: 0,
    unread: 0,
    missing: 0,
    contractor_in_ksef: 0,
    client_invoice_issued: 0,
    client_invoice_ready: 0,
    revenue_ready: null,
    top_reason: null,
    client_report: null,
    ...over,
  };
}

describe("kroki miesiąca klienta", () => {
  it("liczy raporty, RCP, faktury kontraktorów i fakturę do klienta", () => {
    const steps = monthSteps([
      row({ status: "ok" }),
      row({ status: "accepted", contractor_invoice: "in_ksef", client_invoice: "ready" }),
      row({ status: "warnings", issues: "Excel bez maila" }),
      row({ status: "checking" }),
      row({ status: "missing" }),
    ]);
    expect(steps.map((s) => s.value)).toEqual(["4 z 5", "2 bez uwag", "1 w KSeF", "1 do wystawienia"]);
    expect(steps[0].note).toBe("1 bez raportu w poczcie");
    expect(steps[1].note).toBe("1 do decyzji · 1 bez MD · 1 przyjęte");
  });

  it("komplet bez uwag jest zielony", () => {
    const steps = monthSteps([row({ status: "accepted" }), row({ status: "accepted" })]);
    expect(steps[0].tone).toBe("success");
    expect(steps[1].tone).toBe("success");
  });

  it("najczęstsze powody tylko z uwag i odesłanych", () => {
    const reasons = topReasons([
      row({ status: "warnings", issues: "A" }),
      row({ status: "warnings", issues: "A" }),
      row({ status: "needs_fix", issues: "B" }),
      row({ status: "ok", issues: "C" }),
    ]);
    expect(reasons).toEqual([
      ["A", 2],
      ["B", 1],
    ]);
  });

  it("pasek prowadzi do wystawienia faktury za miesiąc, gdy są przyjęte", () => {
    render(<ClientMonthStrip rows={[row({ status: "accepted", client_invoice: "ready" })]} month="2026-10" />);
    expect(screen.getByRole("link", { name: "Wystaw za miesiąc" })).toHaveAttribute(
      "href",
      "/finance?view=sales-invoices&siPeriod=2026-10&siView=issue",
    );
  });

  it("bez osób pasek się nie pokazuje", () => {
    const { container } = render(<ClientMonthStrip rows={[]} month="2026-10" />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("przebieg miesiąca", () => {
  it("adresy prowadzą do klienta i do wystawienia", () => {
    expect(settlementsHref(12, "2026-10")).toBe("/finance?view=settlements&stClient=12&stMonth=2026-10");
    expect(settlementsHref(12, "2026-10", { stSub: "rules" })).toBe(
      "/finance?view=settlements&stClient=12&stMonth=2026-10&stSub=rules",
    );
    expect(issueHref("2026-10")).toBe("/finance?view=sales-invoices&siPeriod=2026-10&siView=issue");
  });

  it("stan faktury do klienta", () => {
    expect(clientInvoiceState(client({ client_invoice_issued: 10 }), true).label).toBe("Wystawiona");
    expect(clientInvoiceState(client({ client_invoice_issued: 4 }), true).label).toBe("Wystawiona częściowo");
    expect(clientInvoiceState(client({ client_invoice_ready: 3, decide: 2 }), true).label).toBe("Do wystawienia");
    expect(clientInvoiceState(client({ clean: 10, revenue_ready: "1000.00" }), true).label).toBe("Po przyjęciu RCP");
    expect(clientInvoiceState(client({ clean: 10, revenue_ready: "1000.00" }), false).note).toBe("10 bez uwag");
    expect(clientInvoiceState(client({ clean: 5, missing: 5 }), true)).toEqual({ tone: "neutral", label: "Czeka", note: "na 5 os." });
  });

  it("powód prowadzi do właściwej podzakładki", () => {
    expect(reasonPlan("proof.accept_has_hours").sub).toBe("rules");
    expect(reasonPlan("missing").who).toBe("Konsultant albo opiekun");
    expect(reasonPlan("Ponad zamówienie o 2 MD").action).toBe("Sprawdź zamówienie");
    expect(reasonPlan("fields.md_hours").action).toBe("Odeślij do poprawy");
  });
});

describe("dla księgowej i przypomnienia", () => {
  it("CSV rezerwy ma średniki i przecinek dziesiętny", () => {
    const csv = reserveCsv([
      { client_id: 1, client: "Klient; A", contract_id: 5, person: "Osoba", md: "20.500", cost: "1000.00" },
      { client_id: 1, client: "Klient B", contract_id: 6, person: "Inna", md: null, cost: null },
    ]);
    expect(csv.split("\n")).toEqual([
      "Klient;Osoba;Kontrakt;MD;Koszt netto",
      '"Klient; A";Osoba;5;20,500;1000,00',
      "Klient B;Inna;6;;",
    ]);
  });

  it("notka przypomnienia: brak adresata ważniejszy niż data", () => {
    const base = { client_id: 1, client_name: "K", missing: 3, automatic: true, to_consultant: 0, to_owner: 3, without_recipient: 0, last_reminder_on: null, mail: { subject: "", text: "" }, rows: [] };
    expect(reminderNote(undefined)).toBeUndefined();
    expect(reminderNote({ ...base, without_recipient: 2, last_reminder_on: "2026-11-05" })).toBe("bez adresata: 2");
    expect(reminderNote({ ...base, last_reminder_on: "2026-11-05" })).toBe("przypomniano 05.11");
    expect(reminderNote(base)).toBe("przypomni automat");
    expect(reminderNote({ ...base, automatic: false })).toBe("bez przypomnienia");
  });
});
