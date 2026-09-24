import { describe, expect, it } from "vitest";

import { boardColumnPurpose } from "@/lib/board-column-purpose";

describe("boardColumnPurpose — „co tu robisz” pod nazwą kolumny (v5)", () => {
  it("każda kolumna Tablicy mówi, co w niej zrobić", () => {
    expect(boardColumnPurpose("new")).toBe("Przejrzyj, zadzwoń, kliknij „Biorę”");
    expect(boardColumnPurpose("screening")).toBe("Arkusz pytań z Championa");
    expect(boardColumnPurpose("verified")).toBe("Stawka ✓ → przygotuj CV do QC");
    expect(boardColumnPurpose("cv_qc")).toBe("Popraw CV, potem wyślij");
    expect(boardColumnPurpose("cv_sent")).toBe("Czekamy na klienta");
    expect(boardColumnPurpose("client_interview")).toBe("Prep → rozmowa → telefon");
    expect(boardColumnPurpose("contract")).toBe("Podpis umowy");
    expect(boardColumnPurpose("hired", { hired: 1, headcount: 3 })).toBe("Obsada 1 / 3");
  });

  it("po weryfikacji następna jest QC CV, nie klient (błąd sprzed v5: „→ CV do klienta”)", () => {
    expect(boardColumnPurpose("verified")).not.toMatch(/klienta/);
    expect(boardColumnPurpose("cv_qc")).not.toMatch(/→ CV do klienta/);
  });

  it("Nordea: kolumna „Wysłane do Cpro” i QC przed przekazaniem do Cpro", () => {
    expect(boardColumnPurpose("cv_sent", { cproEnabled: true })).toBe("CV w Cpro — czekamy na klienta");
    expect(boardColumnPurpose("cv_qc", { cproEnabled: true })).toBe("Popraw CV, potem przekaż do Cpro");
  });

  it("obsada bez liczb mówi „—”, nie zero", () => {
    expect(boardColumnPurpose("hired")).toBe("Obsada — / —");
  });

  it("własny etap szablonu i zamknięci — brak podpisu (zostaje linia SLA)", () => {
    expect(boardColumnPurpose(null)).toBeNull();
    expect(boardColumnPurpose(undefined)).toBeNull();
    expect(boardColumnPurpose("closed")).toBeNull();
  });
});
