import { describe, expect, it } from "vitest";

import { behindLabel, conditionSummary } from "../lifecycle-format";

describe("ścieżki wejścia — warunki i baner „Dociągnij”", () => {
  it("opisuje warunek pozycji, pusty = zawsze", () => {
    expect(conditionSummary({})).toBe("");
    expect(conditionSummary(null)).toBe("");
    expect(conditionSummary({ employment_types: ["b2b"] })).toBe("B2B");
    expect(
      conditionSummary({ employment_types: ["zlecenie"], equipment: "ours", student: true }),
    ).toBe("zlecenie · sprzęt od nas · student");
    expect(conditionSummary({ equipment: "client" })).toBe("sprzęt od klienta");
  });

  it("odmienia liczbę trwających spraw", () => {
    expect(behindLabel(1, "onboarding")).toBe(
      "1 trwające wejście jest na starszej wersji tej ścieżki.",
    );
    expect(behindLabel(3, "onboarding")).toBe(
      "3 trwające wejścia są na starszej wersji tej ścieżki.",
    );
    expect(behindLabel(5, "offboarding")).toBe(
      "5 trwających odejść jest na starszej wersji tej ścieżki.",
    );
  });
});
