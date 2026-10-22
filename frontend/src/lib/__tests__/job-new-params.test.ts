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
    });
    const empty = parseJobPrefill({ hm: "x", skills: "", title: "  " });
    expect(empty).toEqual({ hmId: null, skillIds: [], title: null });
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
