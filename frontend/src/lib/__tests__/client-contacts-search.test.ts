import { describe, expect, it } from "vitest";
import { contactMatches, type SearchableContact } from "@/lib/client-contacts-search";

const base: SearchableContact = {
  name: "Zofia Łęcka",
  email: "zofia.lecka@example.com",
  phone: "600 833 277",
  position: "Kierownik Zespołu",
  department: "Departament Testów",
  notes: null,
  relationship_notes: null,
};

describe("contactMatches", () => {
  it("puste zapytanie pokazuje wszystkich", () => {
    expect(contactMatches(base, "")).toBe(true);
    expect(contactMatches(base, "   ")).toBe(true);
  });

  it("szuka bez polskich znaków i bez wielkości liter", () => {
    expect(contactMatches(base, "lecka")).toBe(true);
    expect(contactMatches(base, "ŁĘCKA")).toBe(true);
  });

  it("każde słowo może trafić w inne pole", () => {
    expect(contactMatches(base, "zofia testow")).toBe(true);
    expect(contactMatches(base, "zofia nordea")).toBe(false);
  });

  it("telefon po samych cyfrach", () => {
    expect(contactMatches(base, "600833")).toBe(true);
    expect(contactMatches(base, "833 277")).toBe(true);
    expect(contactMatches(base, "999")).toBe(false);
  });

  it("krótka liczba nie trafia w telefon przypadkiem", () => {
    expect(contactMatches(base, "60")).toBe(false);
  });

  it("szuka w e-mailu, stanowisku i notatkach; puste pola nie psują", () => {
    expect(contactMatches(base, "example.com")).toBe(true);
    expect(contactMatches(base, "kierownik")).toBe(true);
    const bare: SearchableContact = { ...base, email: null, phone: null, position: null, department: null, notes: "zna Javę" };
    expect(contactMatches(bare, "jave")).toBe(true);
    expect(contactMatches(bare, "600")).toBe(false);
  });
});
