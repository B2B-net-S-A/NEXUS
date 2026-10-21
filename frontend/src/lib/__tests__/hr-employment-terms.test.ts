import { describe, expect, it } from "vitest";

import {
  EMPLOYMENT_TERMS,
  absenceActionLabel,
  coordinatorLabel,
  employmentTerms,
  formOf,
  reportsAbsence,
  timesheetAccusative,
  timesheetCardTitle,
} from "../hr-employment-terms";

// Słowa według formy (etap 2, D4); lustro backendu pilnuje
// `backend/tests/test_hr_employment_terms_mirror.py`.

describe("słownik formy współpracy", () => {
  it("każda forma ma te same słowa, brak formy = umowa o pracę", () => {
    const keys = Object.keys(EMPLOYMENT_TERMS.uop).sort();
    expect(Object.keys(EMPLOYMENT_TERMS.b2b).sort()).toEqual(keys);
    expect(Object.keys(EMPLOYMENT_TERMS.zlecenie).sort()).toEqual(keys);
    expect(formOf(null)).toBe("uop");
    expect(employmentTerms(undefined).absence).toBe("urlop");
  });

  it("B2B i zlecenie: zgłoszenie, koordynator, bez „urlopu” i „wniosku”", () => {
    for (const form of ["b2b", "zlecenie"] as const) {
      expect(reportsAbsence(form)).toBe(true);
      expect(coordinatorLabel(form)).toBe("Koordynator");
      const words = Object.values(EMPLOYMENT_TERMS[form]).join(" ").toLowerCase();
      expect(words).not.toMatch(/urlop|wniosek|przełożon|nadgodzin|premi/);
    }
    expect(reportsAbsence("uop")).toBe(false);
    expect(coordinatorLabel("uop")).toBe("Przełożony");
  });

  it("przyciski i nazwy raportu godzin", () => {
    expect(absenceActionLabel("uop")).toBe("Złóż wniosek urlopowy");
    expect(absenceActionLabel("b2b")).toBe("Zgłoś przerwę");
    expect(absenceActionLabel("zlecenie")).toBe("Zgłoś nieobecność");
    expect(timesheetCardTitle("b2b")).toBe("Raport godzin");
    expect(timesheetCardTitle("zlecenie")).toBe("Potwierdzenie godzin");
    expect(timesheetAccusative("uop")).toBe("ewidencję czasu pracy");
  });

  it("godziny ponad 8 h i wynagrodzenie dodatkowe poza UoP (decyzja Artura 21.10.2026)", () => {
    expect(employmentTerms("uop").overtime).toBe("nadgodziny");
    expect(employmentTerms("uop").overtime_reason).toBe("Uzasadnienie nadgodzin");
    expect(employmentTerms("uop").bonus).toBe("premia");
    expect(employmentTerms("uop").bonuses_tab).toBe("Premie i stawka");
    for (const form of ["b2b", "zlecenie"] as const) {
      const words = employmentTerms(form);
      expect(words.overtime).toBe("godziny ponad 8 h");
      expect(words.overtime_stat).toBe("ponad 8 h dziennie");
      expect(words.overtime_reason).toBe("Czego dotyczyły godziny ponad 8 h");
      expect(words.bonus).toBe("wynagrodzenie dodatkowe");
      expect(words.bonuses).toBe("wynagrodzenie dodatkowe");
      expect(words.bonuses_tab).toBe("Wynagrodzenie dodatkowe i stawka");
    }
    expect(employmentTerms("b2b").overtime_reason_hint).toContain("raporcie godzin");
    expect(employmentTerms("zlecenie").overtime_reason_hint).toContain("potwierdzeniu godzin");
  });
});
