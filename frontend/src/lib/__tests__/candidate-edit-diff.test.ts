import { describe, expect, it } from "vitest";

import { changedCandidateFields, tagChanges } from "@/lib/candidate-edit-diff";

describe("edycja kandydata wysyła tylko zmiany (runda 9, R9-N8-7)", () => {
  it("pomija pola bez zmian, także status i daty", () => {
    const initial = { status: "active", phone: "1", availability_date: "2026-10-01" };
    const next = { status: "active", phone: "2", availability_date: "2026-10-01" };
    expect(changedCandidateFields(initial, next)).toEqual({ phone: "2" });
  });

  it("wysyła tylko zmienione klucze preferencji, wyczyszczony jako null", () => {
    const initial = { preferences: { remote_modes: ["hybrid"], industries: ["Fintech"] } };
    const next = { preferences: { remote_modes: ["hybrid"], industries: null } };
    expect(changedCandidateFields(initial, next)).toEqual({
      preferences: { industries: null },
    });
    expect(changedCandidateFields(initial, { ...initial })).toEqual({});
  });

  it("tagi porównuje bez wielkości liter i bez duplikatów", () => {
    expect(tagChanges("Java, Remote", "java, Go, go")).toEqual({
      add: ["Go"],
      remove: ["Remote"],
    });
    expect(tagChanges("", "")).toEqual({ add: [], remove: [] });
  });
});
