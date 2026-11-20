import { describe, expect, it } from "vitest";

import { careWithoutRhythm, countsAsWard, showMineCareChip, withoutWards } from "../back-office-care";

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
});
