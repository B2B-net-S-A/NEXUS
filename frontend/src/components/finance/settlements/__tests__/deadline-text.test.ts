import { describe, expect, it } from "vitest";

import { deadlineText } from "../format";

const base = { date: "2026-11-15", people: [] as string[] };

describe("deadlineText (termin faktury z T4T)", () => {
  it("odmienia dni i osoby", () => {
    expect(deadlineText({ ...base, days_left: 1, overdue: false, missing: 5 })).toBe(
      "Do terminu faktury 15.11 został 1 dzień: 5 osób bez zatwierdzonych godzin w T4T.",
    );
    expect(deadlineText({ ...base, days_left: 5, overdue: false, missing: 22 })).toBe(
      "Do terminu faktury 15.11 zostało 5 dni: 22 osoby bez zatwierdzonych godzin w T4T.",
    );
  });

  it("dziś i po terminie", () => {
    expect(deadlineText({ ...base, days_left: 0, overdue: false, missing: 1 })).toBe(
      "Dziś termin faktury (15.11): 1 osoba bez zatwierdzonych godzin w T4T.",
    );
    expect(deadlineText({ ...base, days_left: -2, overdue: true, missing: 13 })).toBe(
      "Termin faktury minął 15.11 (2 dni temu): 13 osób bez zatwierdzonych godzin w T4T.",
    );
  });
});
