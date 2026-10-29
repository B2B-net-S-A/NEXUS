import { describe, expect, it } from "vitest";

import type { Opportunity, OpportunityEvent, Stage } from "@/lib/api/sales";

import { localInputToIso } from "../ActivityTimeline";
import { duplicatesFromError } from "../CompanyFormDialog";
import { daysLabel, daysSince, formatDealAmount, formatDealNumber, safeHref } from "../format";
import { boardStages, summarize } from "../OpportunitiesView";
import { describeEvent } from "../OpportunityHistory";
import { parseAmount, parseRoles, rolesToText } from "../OpportunityFormDialog";
import { datesNote, period } from "../WhoWeKnowPanel";

const stage = (id: number, outcome: Stage["outcome"]): Stage => ({
  id,
  key: `s${id}`,
  name: `Etap ${id}`,
  position: id,
  probability: 0,
  outcome,
  qualifies: false,
  color: null,
});

const opp = (status: Opportunity["status"], value: string | null, weighted: string | null) =>
  ({ status, value, weighted_value: weighted }) as Opportunity;

describe("Sprzedaż — kwoty i dni", () => {
  it("wartość szansy bez groszy, pusta jako kreska", () => {
    expect(formatDealAmount("45000.40")).toMatch(/^45\s000 zł$/);
    expect(formatDealNumber(null)).toBe("—");
    expect(formatDealAmount("")).toBe("—");
  });

  it("link zewnętrzny tylko dla http(s)", () => {
    expect(safeHref("https://bank.example.com")).toBe("https://bank.example.com");
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref("data:text/html,x")).toBeUndefined();
    expect(safeHref(null)).toBeUndefined();
  });

  it("dni od ostatniej aktywności", () => {
    const now = Date.parse("2026-10-26T12:00:00Z");
    expect(daysSince("2026-10-11T12:00:00Z", now)).toBe(15);
    expect(daysSince(null, now)).toBeNull();
    expect(daysLabel(0)).toBe("dziś");
    expect(daysLabel(1)).toBe("1 dzień");
    expect(daysLabel(15)).toBe("15 dni");
  });
});

describe("Sprzedaż — tablica szans", () => {
  it("liczy tylko otwarte do lejka, wygrane osobno", () => {
    expect(
      summarize([opp("open", "100", "60"), opp("open", null, null), opp("won", "999", "999"), opp("lost", "5", "0")]),
    ).toEqual({ open: 2, value: 100, weighted: 60, won: 1 });
  });

  it("przegrane etapy nie są kolumnami tablicy", () => {
    expect(boardStages([stage(1, "open"), stage(2, "lost"), stage(3, "won")]).map((s) => s.id)).toEqual([1, 3]);
  });
});

describe("Sprzedaż — formularze", () => {
  it("kwota z polskim zapisem i odrzuceniem tekstu", () => {
    expect(parseAmount("40 000,50")).toBe("40000.50");
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("dużo")).toBeNull();
  });

  it("role z jednej linii", () => {
    expect(parseRoles("3 × Test Automation, 2x QA; lider")).toEqual([
      { count: 3, title: "Test Automation" },
      { count: 2, title: "QA" },
      { count: 1, title: "lider" },
    ]);
  });

  it("role w edycji wracają do tej samej linii", () => {
    const roles = [
      { count: 3, title: "Test Automation" },
      { count: 1, title: "lider" },
    ];
    expect(rolesToText(roles)).toBe("3 × Test Automation, 1 × lider");
    expect(parseRoles(rolesToText(roles))).toEqual(roles);
  });

  it("duplikaty czytane z odpowiedzi 409", () => {
    const error = {
      response: {
        status: 409,
        data: { detail: { code: "sales_company_duplicate", duplicates: [{ id: 7, name: "Bank Przykładowy", nip: null }] } },
      },
    };
    expect(duplicatesFromError(error)).toEqual([{ id: 7, name: "Bank Przykładowy", nip: null }]);
    expect(duplicatesFromError({ response: { data: { detail: "Nie" } } })).toEqual([]);
    expect(duplicatesFromError(null)).toEqual([]);
  });

  it("pusty termin zadania to brak terminu", () => {
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("2026-10-30T09:30")).toMatch(/^2026-10-30T\d{2}:30:00\.000Z$/);
  });
});

describe("Sprzedaż — „Kogo znamy”", () => {
  it("okres z CV: koniec bez roku to „teraz”", () => {
    expect(period({ period: { start: "2019", end: "2022" } })).toBe("2019–2022");
    expect(period({ period: { start: "2023-07", end: "present" } })).toBe("2023-07–teraz");
    expect(period({ period: { start: "2024", end: null } })).toBe("2024–teraz");
    expect(period({ period: null })).toBeNull();
  });

  it("stan uzupełniania dat mówi, co się dzieje", () => {
    expect(datesNote(null)).toBeNull();
    expect(datesNote({ status: "running", total: 120 })).toBe("Uzupełniamy daty 120 osób z CV…");
    expect(datesNote({ status: "done", total: 7, updated: 7 })).toBe("Daty uzupełnione: 7 z 7 osób");
    expect(datesNote({ status: "partial", total: 9, updated: 3 })).toContain("przerwane");
    expect(datesNote({ status: "failed" })).toContain("nie powiodło się");
  });
});

const event = (patch: Partial<OpportunityEvent>): OpportunityEvent => ({
  id: 1,
  kind: "updated",
  field: null,
  old_value: null,
  new_value: null,
  old_label: null,
  new_label: null,
  user: null,
  created_at: "2026-10-28T12:00:00Z",
  ...patch,
});

describe("Sprzedaż — historia zmian szansy", () => {
  it("etap i opiekun po nazwie, usunięty etap jako identyfikator", () => {
    expect(
      describeEvent(
        event({ field: "stage_id", old_value: "1", new_value: "4", old_label: "Lead", new_label: "Oferta wysłana" }),
      ),
    ).toBe("Etap: Lead → Oferta wysłana");
    expect(describeEvent(event({ field: "stage_id", old_value: "9", new_value: "4", new_label: "Wygrana" }))).toBe(
      "Etap: #9 → Wygrana",
    );
  });

  it("kwoty, marża, data i status po polsku, puste jako kreska", () => {
    expect(describeEvent(event({ field: "value", old_value: "40000", new_value: "45000" }))).toMatch(
      /^Wartość: 40\s000 zł → 45\s000 zł$/,
    );
    expect(describeEvent(event({ field: "margin_pct", old_value: "20", new_value: "22.5" }))).toBe(
      "Marża: 20% → 22.5%",
    );
    expect(describeEvent(event({ field: "expected_close_date", new_value: "2026-12-15" }))).toBe(
      "Planowane zamknięcie: — → 15.12.2026",
    );
    expect(describeEvent(event({ field: "status", old_value: "open", new_value: "lost" }))).toBe(
      "Status: otwarta → przegrana",
    );
  });

  it("założenie, archiwum i scalenie firm", () => {
    expect(describeEvent(event({ kind: "created", field: "stage_id", new_value: "1", new_label: "Lead" }))).toBe(
      "Założenie szansy na etapie „Lead”",
    );
    expect(describeEvent(event({ kind: "archived" }))).toBe("Przeniesienie do archiwum");
    expect(
      describeEvent(
        event({ kind: "company_merged", field: "company_id", old_value: "2", new_value: "3", old_label: "A", new_label: "B" }),
      ),
    ).toBe("Scalenie firm: A → B");
  });
});
