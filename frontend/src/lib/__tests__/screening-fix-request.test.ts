import { describe, expect, it } from "vitest";

import type { ScreeningFixRequest } from "@/lib/api/screeningForm";
import { fixFieldDirty, fixFieldState } from "@/lib/screening-fix-request";

const request: ScreeningFixRequest = {
  version_no: 2,
  stage_id: 9,
  requested_at: null,
  requested_by_name: null,
  remark: null,
  fields: [
    { key: "question:q1", label: "Pytanie 1", changed: false },
    { key: "field:availability", label: "Dostępność", changed: true },
    { key: "candidate_rate", label: "Stawka", changed: false },
    { key: "field:overall_fit", label: "Ocena", changed: false },
  ],
  count: 4,
  changed_count: 1,
};

describe("stan pola w prośbie DL o poprawki (D6)", () => {
  it("zapisana poprawka wygrywa, potem niezapisana zmiana, na końcu „do poprawy”", () => {
    const dirty = { answers: { q1: { response: true } }, rate_amount: true };
    expect(fixFieldState(request, "field:availability", dirty)).toBe("done");
    expect(fixFieldState(request, "question:q1", dirty)).toBe("edited");
    expect(fixFieldState(request, "candidate_rate", dirty)).toBe("edited");
    expect(fixFieldState(request, "field:overall_fit", dirty)).toBe("todo");
    // Pole spoza prośby nie ma znacznika.
    expect(fixFieldState(request, "field:red_flags", dirty)).toBeNull();
    expect(fixFieldState(null, "question:q1", dirty)).toBeNull();
  });

  it("dirtyFields react-hook-form po kluczu prośby", () => {
    expect(fixFieldDirty("field:recommendation", { card: { recommendation: true } })).toBe(true);
    expect(fixFieldDirty("field:overall_fit", { overall_fit: true })).toBe(true);
    expect(fixFieldDirty("question:q2", { answers: { q1: { response: true } } })).toBe(false);
    expect(fixFieldDirty("cv", { card: {} })).toBe(false);
    expect(fixFieldDirty("question:q1", undefined)).toBe(false);
  });
});
