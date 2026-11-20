import { describe, expect, it } from "vitest";

import { backOfficeTab } from "@/components/care/CareScreen";
import type { BoConsultantRow } from "@/lib/api/back-office";

import { daysToEnd, matchesQuick, silentFor } from "../ConsultantsTab";

function row(fields: Partial<BoConsultantRow> = {}): BoConsultantRow {
  return {
    contract_id: 1,
    client_id: 2,
    client_name: "Firma Testowa",
    name: "Jan Przykładowy",
    job_title: null,
    contract_type: "b2b",
    start_date: "2025-01-01",
    end_date: null,
    end_source: null,
    open_cases: [],
    last_conversation: null,
    ...fields,
  };
}

describe("układ modułu: jeden zespół (19.11.2026)", () => {
  it("stare zakładki Rozmowy, Jakość, FAQ, Przegląd i Zespoły prowadzą do Zespołu kierownika", () => {
    for (const tab of ["teams", "team", "review", "talks", "quality", "faq"] as const) {
      expect(backOfficeTab(tab, { lead: true, careRole: true })).toBe("teams");
      expect(backOfficeTab(tab, { lead: false, careRole: true })).toBe("todo");
    }
  });

  it("Konsultanci i Klienci są dla całego zespołu, Komunikaty tylko z rolą opieki", () => {
    expect(backOfficeTab("consultants", { lead: false, careRole: false })).toBe("consultants");
    expect(backOfficeTab("clients", { lead: false, careRole: false })).toBe("clients");
    expect(backOfficeTab("announcements", { lead: false, careRole: true })).toBe("announcements");
    expect(backOfficeTab("announcements", { lead: false, careRole: false })).toBe("todo");
    expect(backOfficeTab("todo", { lead: true, careRole: true })).toBe("todo");
  });
});

describe("Konsultanci bez opiekuna: filtry", () => {
  const today = "2026-11-20";

  it("kończą w 60 dni liczy od dziś, bez już zakończonych i bez daty", () => {
    expect(matchesQuick(row({ end_date: "2026-12-31" }), "ending", today)).toBe(true);
    expect(matchesQuick(row({ end_date: "2027-03-01" }), "ending", today)).toBe(false);
    expect(matchesQuick(row({ end_date: "2026-11-01" }), "ending", today)).toBe(false);
    expect(matchesQuick(row(), "ending", today)).toBe(false);
    expect(daysToEnd(row({ end_date: "2026-11-30" }), today)).toBe(10);
  });

  it("bez rozmowy > 90 dni obejmuje także osoby, z którymi nikt nie rozmawiał", () => {
    expect(matchesQuick(row(), "silent", today)).toBe(true);
    expect(matchesQuick(row({ last_conversation: { on: "2026-11-01", by: null } }), "silent", today)).toBe(false);
    expect(matchesQuick(row({ last_conversation: { on: "2026-04-30", by: null } }), "silent", today)).toBe(true);
    expect(silentFor(row({ last_conversation: { on: "2026-11-10", by: null } }), today)).toBe(10);
  });

  it("z otwartą sprawą = co najmniej jedna karta w kolejce", () => {
    expect(matchesQuick(row(), "with_case", today)).toBe(false);
    expect(matchesQuick(row({ open_cases: [{ id: 5, lane: "exit", label: "Wyjście" }] }), "with_case", today)).toBe(true);
  });
});
