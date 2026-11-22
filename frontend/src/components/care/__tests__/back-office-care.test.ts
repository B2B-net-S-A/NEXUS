import { describe, expect, it } from "vitest";

import {
  careWithoutRhythm,
  countsAsWard,
  nearestPlanItem,
  planItemOverdue,
  showMineCareChip,
  withoutWards,
} from "../back-office-care";

const modules = (backOffice: boolean) =>
  ({ open_modules: { back_office: backOffice } }) as unknown as Parameters<typeof careWithoutRhythm>[0];

describe("Opieka przy module back office (20.11.2026)", () => {
  it("bez rytmu tylko z włączonym modułem", () => {
    expect(careWithoutRhythm(modules(true))).toBe(true);
    expect(careWithoutRhythm(modules(false))).toBe(false);
  });

  it("bez podopiecznych dopiero po wczytaniu listy i tylko przy module", () => {
    expect(withoutWards(true, [{ is_mine: false }, { is_mine: false }])).toBe(true);
    expect(withoutWards(true, [])).toBe(true);
    expect(withoutWards(true, [{ is_mine: false }, { is_mine: true }])).toBe(false);
    // Lista w drodze — nie przełączamy zakresu na ślepo.
    expect(withoutWards(true, null)).toBe(false);
    // Bez modułu DL ma podopiecznych z łańcucha jak dotąd.
    expect(withoutWards(false, [{ is_mine: false }])).toBe(false);
  });

  it("chip „Moi podopieczni” przy module tylko z podopiecznymi albo włączony", () => {
    expect(showMineCareChip(false, 0, false)).toBe(true);
    expect(showMineCareChip(true, 0, false)).toBe(false);
    expect(showMineCareChip(true, null, false)).toBe(false);
    expect(showMineCareChip(true, 3, false)).toBe(true);
    expect(showMineCareChip(true, 0, true)).toBe(true);
  });

  it("przy module do podopiecznych liczą się tylko karty konsultanta", () => {
    expect(countsAsWard("contact", true)).toBe(true);
    expect(countsAsWard("decision", true)).toBe(true);
    expect(countsAsWard("feedback", true)).toBe(false);
    expect(countsAsWard("demand", true)).toBe(false);
    expect(countsAsWard("data", true)).toBe(false);
    // Bez modułu jak dotąd: każda karta z czytającym jako opiekunem.
    expect(countsAsWard("feedback", false)).toBe(true);
  });

  it("rozmowa z rytmu przy module nie jest „po terminie”, kamienie dalej tak", () => {
    const today = "2026-11-20";
    const cadence = { kind: "cadence" as const, status: "open" as const, due_on: "2026-10-05" };
    const day7 = { kind: "day_7" as const, status: "open" as const, due_on: "2026-11-10" };
    expect(planItemOverdue(cadence, today, true)).toBe(false);
    expect(planItemOverdue(day7, today, true)).toBe(true);
    // Bez modułu jak dotąd.
    expect(planItemOverdue(cadence, today, false)).toBe(true);
    // Zamknięty albo z terminem od dziś — nigdy po terminie.
    expect(planItemOverdue({ ...day7, status: "done" }, today, false)).toBe(false);
    expect(planItemOverdue({ ...cadence, due_on: today }, today, false)).toBe(false);
  });

  it("„najbliższy” przy module pomija rozmowy z rytmu sprzed dziś", () => {
    const today = "2026-11-20";
    const stale = { id: 1, kind: "cadence" as const, status: "open" as const, due_on: "2026-10-05" };
    const preEnd = { id: 2, kind: "pre_end" as const, status: "open" as const, due_on: "2026-12-01" };
    const future = { id: 3, kind: "cadence" as const, status: "open" as const, due_on: "2026-12-10" };
    expect(nearestPlanItem([stale, preEnd, future], today, true)?.id).toBe(2);
    expect(nearestPlanItem([stale], today, true)).toBeNull();
    expect(nearestPlanItem([stale, preEnd], today, false)?.id).toBe(1);
    expect(nearestPlanItem([], today, false)).toBeNull();
  });
});
