import { describe, expect, it } from "vitest";
import {
  candidateGridLayout,
  toggleCandidateColumn,
  visibleCandidateColumns,
} from "@/lib/candidate-table-columns";

const ids = (hidden: string[] | null) => visibleCandidateColumns(hidden).map((c) => c.id);

describe("kolumny tabeli kandydatów", () => {
  it("domyślnie ukrywa dodatkowe kolumny", () => {
    expect(ids(null)).toEqual([
      "candidate",
      "position",
      "phone",
      "rate",
      "availability",
      "process",
      "cv",
      "assign",
    ]);
  });

  it("kolumn wymaganych nie da się ukryć, nieznane id są ignorowane", () => {
    expect(ids(["candidate", "assign", "nieznana"])).toContain("candidate");
    expect(ids(["candidate", "assign"])).toContain("assign");
  });

  it("przełączenie dokłada i zdejmuje kolumnę", () => {
    const withEmail = toggleCandidateColumn(null, "email");
    expect(ids(withEmail)).toContain("email");
    const withoutPhone = toggleCandidateColumn(withEmail, "phone");
    expect(ids(withoutPhone)).not.toContain("phone");
    expect(toggleCandidateColumn(withoutPhone, "phone")).not.toContain("phone");
  });

  it("szablon siatki ma kolumnę zaznaczenia i sumę minimalnych szerokości", () => {
    const layout = candidateGridLayout(visibleCandidateColumns(null));
    expect(layout.template.startsWith("32px ")).toBe(true);
    expect(layout.minWidth).toBe(32 + 168 + 150 + 132 + 72 + 88 + 112 + 52 + 104);
  });
});
