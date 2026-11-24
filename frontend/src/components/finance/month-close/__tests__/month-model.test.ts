import { describe, expect, it } from "vitest";

import type {
  MonthCloseClient,
  MonthCloseOverview,
  MonthCloseStages,
  SettlementRow,
  TeamMonthPerson,
} from "@/lib/api/client-settlements";

import {
  automatAnswer,
  clientInvoiceLook,
  clientMoves,
  personSteps,
  problemTotal,
  teamMoves,
  teamSteps,
  teamSummary,
} from "../month-model";

function stages(over: Partial<MonthCloseStages> = {}): MonthCloseStages {
  return {
    people: 10,
    report: { in: 8, missing: 2 },
    check: { clean: 4, warn: 1, fail: 1, returned: 0, unread: 1, no_md: 1, missing: 2 },
    accept: { done: 0, auto: 0, ready: 4 },
    contractor_invoice: { match: 0, differs: 0, nip: 1, can_issue: 0, none: 9 },
    client_invoice: { issued: 0, ready: 0, waiting_client: 0, waiting: 10, issued_early: 0 },
    missing_order: 0,
    ...over,
  };
}

function client(over: Partial<MonthCloseClient> = {}): MonthCloseClient {
  return {
    client_id: 1,
    name: "Klient A",
    people: 10,
    clean: 4,
    accepted: 0,
    decide: 2,
    unread: 2,
    missing: 2,
    contractor_in_ksef: 0,
    client_invoice_issued: 0,
    client_invoice_ready: 0,
    revenue_ready: null,
    top_reason: null,
    client_report: null,
    stages: stages(),
    ...over,
  };
}

function row(over: Partial<SettlementRow> = {}): SettlementRow {
  return {
    contract_id: 1,
    settlement_id: 1,
    person: "Osoba A",
    order_number: "Z-1",
    status: "ok",
    issues: null,
    issue_level: null,
    md_regular: "21",
    md_extra: null,
    md_charged: "21",
    md_remaining_after: null,
    amount_cost: null,
    amount_revenue: null,
    margin: null,
    margin_pct: null,
    contractor_invoice: "none",
    client_invoice: "waiting",
    ...over,
  };
}

describe("kroki osoby", () => {
  it("błąd blokuje przyjęcie, uwagę Finanse mogą przyjąć", () => {
    const fail = personSteps(row({ status: "warnings", issue_level: "fail", issues: "Sumy MD" }));
    expect(fail.check).toMatchObject({ tone: "fail", label: "Błąd", note: "Sumy MD" });
    expect(fail.accept.label).toBe("—");
    const warn = personSteps(row({ status: "warnings", issue_level: "warn", issues: "Excel bez maila" }));
    expect(warn.check).toMatchObject({ tone: "warn", label: "Uwaga" });
    expect(warn.accept).toMatchObject({ tone: "todo", label: "Po decyzji" });
    expect(warn.who.label).toBe("Finanse");
  });

  it("uwaga bez opisu prowadzi do karty zamiast pustej komórki", () => {
    expect(personSteps(row({ status: "warnings", issue_level: null })).check.note).toBe("bez opisu — otwórz kartę");
  });

  it("brak MD na zamówieniu to sprawa opiekuna, nie nieodczytany plik", () => {
    const s = personSteps(row({ status: "no_md", issues: "Brak linii zamówienia" }));
    expect(s.check.label).toBe("Zamówienie bez MD");
    expect(s.who.label).toBe("Opiekun");
    expect(personSteps(row({ status: "checking" })).check.label).toBe("Nieodczytany");
  });

  it("faktura do klienta przed przyjęciem RCP jest ostrzeżeniem", () => {
    expect(personSteps(row({ status: "ok", client_invoice: "issued" })).client).toMatchObject({
      tone: "warn",
      note: "przed przyjęciem RCP",
    });
    expect(personSteps(row({ status: "accepted", client_invoice: "issued", contractor_invoice: "in_ksef" })).client.tone).toBe("done");
  });

  it("przyjęte przez automat i czekające na fakturę kontraktora", () => {
    const s = personSteps(row({ status: "accepted", accepted_auto: true }));
    expect(s.accept.label).toBe("Przyjął automat");
    expect(s.contractor.label).toBe("Czeka na fakturę");
    expect(s.who.label).toBe("Konsultant");
  });
});

describe("klient w miesiącu", () => {
  it("faktura wstrzymana, częściowa i wystawiona", () => {
    expect(clientInvoiceLook(client()).key).toBe("blocked");
    const part = clientInvoiceLook(
      client({ stages: stages({ client_invoice: { issued: 4, ready: 0, waiting_client: 0, waiting: 6, issued_early: 4 } }) }),
    );
    expect(part).toMatchObject({ key: "partial", tone: "warn", note: "4 przed przyjęciem RCP" });
    const all = clientInvoiceLook(
      client({ stages: stages({ client_invoice: { issued: 10, ready: 0, waiting_client: 0, waiting: 0, issued_early: 0 } }) }),
    );
    expect(all.key).toBe("issued");
    expect(clientInvoiceLook(client({ client_report: { all: 5, ok: 5, differs: 0, unmatched: 0, no_invoice: 0 } })).key).toBe("report");
  });

  it("kto teraz: najpierw Finanse, potem konsultanci i opiekun", () => {
    const moves = clientMoves(stages());
    expect(moves.map((m) => m.who)).toEqual(["Finanse", "Konsultanci", "Opiekun"]);
    // 1 błąd + 1 uwaga + 1 nieodczytany + 4 do przyjęcia + 1 NIP
    expect(moves[0]).toMatchObject({ count: 8, tone: "fail" });
    expect(clientMoves(stages({ report: { in: 10, missing: 0 }, check: { clean: 10, warn: 0, fail: 0, returned: 0, unread: 0, no_md: 0, missing: 0 }, accept: { done: 10, auto: 0, ready: 0 }, contractor_invoice: { match: 10, differs: 0, nip: 0, can_issue: 0, none: 0 } }))).toEqual([]);
  });

  it("co jest źle nie liczy braków raportu", () => {
    expect(problemTotal(stages())).toBe(4);
  });

  it("automat: lejek od raportu do reguł bez uwag", () => {
    const data = { clients: [client()], stages: stages(), reasons: [], month: "2026-10", can_see_amounts: false, totals: {} } as unknown as MonthCloseOverview;
    const a = automatAnswer(data, null);
    expect(a).toMatchObject({ people: 10, clean: 4, pct: 40 });
    expect(a.steps.map((s) => [s.value, s.of])).toEqual([
      [8, 10],
      [7, 8],
      [4, 7],
      [0, 4],
      [1, 10],
    ]);
  });
});

describe("biuro", () => {
  const person = (over: Partial<TeamMonthPerson>): TeamMonthPerson => ({
    user_id: 1,
    person: "Osoba B",
    timesheet: "approved",
    timesheet_on: "2026-11-05",
    invoice: "in_ksef",
    invoice_on: "2026-11-03",
    paid: false,
    paid_on: null,
    ...over,
  });

  it("bez faktury do klienta, ruch po stronie osoby albo Finansów", () => {
    const s = teamSteps(person({}));
    expect(s.client).toMatchObject({ tone: "na", label: "Nie dotyczy" });
    expect(s.contractor).toMatchObject({ tone: "done", label: "W KSeF 03.11", note: "do zapłaty" });
    expect(s.who).toMatchObject({ label: "Finanse", note: "zapłata" });
    expect(teamSteps(person({ timesheet: "missing", invoice: "missing" })).who).toMatchObject({ label: "Osoba", note: "ewidencja" });
    expect(teamSteps(person({ paid: true, paid_on: "2026-11-10" })).who.label).toBe("Zamknięte");
  });

  it("podsumowanie biura", () => {
    const t = teamSummary({
      month: "2026-10",
      people: [person({}), person({ user_id: 2, paid: true }), person({ user_id: 3, timesheet: "missing", invoice: "missing" })],
    });
    expect(t).toEqual({ people: 3, timesheets: 2, approved: 2, invoices: 2, differs: 0, paid: 1, noNip: 0 });
  });

  it("bez NIP-u to sprawa Płac, a nie brak faktury od osoby", () => {
    const noNip = person({ invoice: "no_nip", invoice_on: null });
    expect(teamSteps(noNip).contractor).toMatchObject({ tone: "fail", label: "Brak NIP-u" });
    expect(teamSteps(noNip).who).toMatchObject({ label: "Płace", note: "NIP osoby" });
    const t = teamSummary({ month: "2026-10", people: [noNip, person({ user_id: 2, invoice: "missing", invoice_on: null })] });
    expect(t).toMatchObject({ invoices: 0, noNip: 1 });
    expect(teamMoves(t).map((m) => [m.who, m.count])).toEqual([
      ["Płace (NIP)", 1],
      ["Osoby", 1],
    ]);
  });
});
