/**
 * `/jobs/new?client=&hm=&skills=&title=` (22.10.2026): parametry wypełniają
 * wyłącznie PUSTE pola (reguła D3 odczytu requestu) — wpisany tytuł,
 * wybrany hiring manager, „Klient nie podał” i wpisane wymagania zostają.
 */
import { describe, expect, it } from "vitest";

import {
  applyJobPrefill,
  hasJobPrefill,
  parseJobPrefill,
  skillNamesFor,
} from "@/lib/job-new-params";
import { EMPTY_INTAKE_FORM } from "@/lib/job-request-intake";
import { filledRows } from "@/lib/requirement-rows";

const VALUES = {
  title: "Java Developer",
  hiringManager: { id: 345, name: "Katarzyna Płatnicza" },
  skills: ["Java 17", "Kafka"],
};

describe("parseJobPrefill", () => {
  it("czyta id menedżera, listę umiejętności bez powtórzeń i tytuł; śmieci to brak", () => {
    expect(parseJobPrefill({ hm: "345", skills: "1,2,2,abc,0", title: " Java " })).toEqual({
      hmId: 345,
      skillIds: [1, 2],
      title: "Java",
      department: null,
      headcount: null,
      startMonth: null,
    });
    const empty = parseJobPrefill({ hm: "x", skills: "", title: "  ", headcount: "0", start: "2027-13" });
    expect(empty).toEqual({
      hmId: null,
      skillIds: [],
      title: null,
      department: null,
      headcount: null,
      startMonth: null,
    });
    expect(hasJobPrefill(empty)).toBe(false);
  });

  it("nazwy umiejętności w kolejności z adresu, nieznane id odpadają", () => {
    expect(
      skillNamesFor([3, 1, 9], [
        { skill_id: 1, name: "Java 17" },
        { skill_id: 3, name: "Kafka" },
      ]),
    ).toEqual(["Kafka", "Java 17"]);
  });
});

describe("parseJobPrefill · popyt (R4)", () => {
  it("dział, liczba osób 1–99 i miesiąc „RRRR-MM”; reszta to brak", () => {
    const prefill = parseJobPrefill({ dept: "  Płatności  ", headcount: "2", start: "2027-01" });
    expect(prefill).toMatchObject({ department: "Płatności", headcount: 2, startMonth: "2027-01" });
    expect(hasJobPrefill(prefill)).toBe(true);
    expect(parseJobPrefill({ headcount: "120" }).headcount).toBeNull();
    expect(parseJobPrefill({ start: "styczeń" }).startMonth).toBeNull();
  });
});

describe("applyJobPrefill", () => {
  it("pusty formularz bierze tytuł, menedżera i wymagania „musi mieć”", () => {
    const form = applyJobPrefill({ ...EMPTY_INTAKE_FORM }, VALUES);
    expect(form.title).toBe("Java Developer");
    expect(form.hiringManager).toEqual({ kind: "contact", id: 345, name: "Katarzyna Płatnicza" });
    expect(filledRows(form.rows).map((row) => [row.words, row.level])).toEqual([
      [["Java 17"], "must"],
      [["Kafka"], "must"],
    ]);
  });

  it("liczba osób, start i dział wchodzą tylko w puste pola", () => {
    const extra = { ...VALUES, department: "Płatności", headcount: 2, startMonth: "2027-01" };
    const form = applyJobPrefill({ ...EMPTY_INTAKE_FORM }, extra);
    expect(form.headcount).toBe("2");
    expect(form.startDate).toBe("2027-01-01");
    expect(form.about).toBe("Dział u klienta: Płatności.");
    const typed = { ...EMPTY_INTAKE_FORM, headcount: "3", startDate: "2026-12-01", about: "Projekt X" };
    const kept = applyJobPrefill(typed, { ...extra, title: null, hiringManager: null, skills: [] });
    expect(kept).toBe(typed);
  });

  it("wpisane pola zostają, „Klient nie podał” blokuje menedżera", () => {
    const typed = {
      ...EMPTY_INTAKE_FORM,
      title: "Analityk",
      hiringManagerNotProvided: true,
      rows: [{ key: "r1", words: ["SQL"], level: "nice" as const }],
    };
    const form = applyJobPrefill(typed, VALUES);
    expect(form).toBe(typed);
  });
});
