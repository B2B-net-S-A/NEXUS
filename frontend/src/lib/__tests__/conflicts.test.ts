import { describe, expect, it } from "vitest";

import {
  canSubmitDeactivation,
  conflictKeys,
  conflictState,
  eligibilityBadgeClass,
  expiresAtIso,
  formatExpiry,
  minExpiryDateInput,
  validateConflictForm,
  type ConflictFormValues,
} from "@/lib/conflicts";

const NOW = new Date(2026, 8, 17, 12, 0, 0); // 17.09.2026, 12:00 lokalnie

function values(overrides: Partial<ConflictFormValues> = {}): ConflictFormValues {
  return { client_id: "5", type: "blacklist", reason: "", expires_on: "", ...overrides };
}

describe("conflictKeys", () => {
  it("every key starts with the shared prefix, so one invalidation refreshes all", () => {
    expect(conflictKeys.candidate(1, false).slice(0, 1)).toEqual(conflictKeys.all);
    expect(conflictKeys.registry({ client_id: 3 }).slice(0, 1)).toEqual(conflictKeys.all);
    expect(conflictKeys.candidate(1, false)).not.toEqual(conflictKeys.candidate(1, true));
  });
});

describe("formatExpiry", () => {
  it("future date → 'wygasa DD.MM.RRRR' in Europe/Warsaw", () => {
    expect(formatExpiry("2026-10-01T10:00:00Z", NOW)).toBe("wygasa 01.10.2026");
  });

  it("past date → 'wygasł DD.MM.RRRR'", () => {
    expect(formatExpiry("2026-09-01T10:00:00Z", NOW)).toBe("wygasł 01.09.2026");
  });

  it("uses Warsaw calendar day, not UTC (22:30 UTC on 30.09 is 01.10 in Warsaw)", () => {
    expect(formatExpiry("2026-09-30T22:30:00Z", NOW)).toBe("wygasa 01.10.2026");
  });

  it("no date or garbage → null", () => {
    expect(formatExpiry(null, NOW)).toBeNull();
    expect(formatExpiry(undefined, NOW)).toBeNull();
    expect(formatExpiry("not-a-date", NOW)).toBeNull();
  });
});

describe("expiresAtIso", () => {
  it("returns the END of the chosen local day as a full ISO string", () => {
    const iso = expiresAtIso("2026-10-01");
    expect(iso).not.toBeNull();
    const d = new Date(iso!);
    expect(d.getFullYear()).toBe(2026);
    expect(d.getMonth()).toBe(9);
    expect(d.getDate()).toBe(1);
    expect(d.getHours()).toBe(23);
    expect(d.getMinutes()).toBe(59);
    expect(iso).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });

  it("empty or invalid input → null", () => {
    expect(expiresAtIso("")).toBeNull();
    expect(expiresAtIso(null)).toBeNull();
    expect(expiresAtIso("2026-02-30")).toBeNull();
    expect(expiresAtIso("01.10.2026")).toBeNull();
  });
});

describe("minExpiryDateInput", () => {
  it("is tomorrow, also across a month boundary", () => {
    expect(minExpiryDateInput(NOW)).toBe("2026-09-18");
    expect(minExpiryDateInput(new Date(2026, 8, 30, 23, 0))).toBe("2026-10-01");
  });
});

describe("validateConflictForm", () => {
  it("requires a client", () => {
    expect(validateConflictForm(values({ client_id: "" }), NOW)).toEqual({
      client_id: "Wybierz klienta.",
    });
  });

  it("NDA requires an expiry date", () => {
    expect(validateConflictForm(values({ type: "nda" }), NOW)).toEqual({
      expires_on: "NDA wymaga daty wygaśnięcia.",
    });
  });

  it("other types accept no date", () => {
    for (const type of ["blacklist", "competitor", "current_employment"] as const) {
      expect(validateConflictForm(values({ type }), NOW)).toEqual({});
    }
  });

  it("today or the past is rejected; tomorrow passes", () => {
    expect(validateConflictForm(values({ expires_on: "2026-09-17" }), NOW)).toEqual({
      expires_on: "Data wygaśnięcia musi być w przyszłości.",
    });
    expect(validateConflictForm(values({ expires_on: "2025-01-01" }), NOW).expires_on).toBe(
      "Data wygaśnięcia musi być w przyszłości.",
    );
    expect(
      validateConflictForm(values({ type: "nda", expires_on: "2026-09-18" }), NOW),
    ).toEqual({});
  });

  it("a malformed date gets its own message", () => {
    expect(validateConflictForm(values({ expires_on: "2026-13-01" }), NOW).expires_on).toBe(
      "Podaj poprawną datę wygaśnięcia.",
    );
  });
});

describe("conflictState", () => {
  it("prefers the server-computed state", () => {
    expect(conflictState({ state: "expired", active: true, expires_at: null }, NOW)).toBe(
      "expired",
    );
  });

  it("falls back to active/expires_at for older payloads", () => {
    expect(conflictState({ active: false, expires_at: null }, NOW)).toBe("inactive");
    expect(conflictState({ active: true, expires_at: "2026-09-01T00:00:00Z" }, NOW)).toBe(
      "expired",
    );
    expect(conflictState({ active: true, expires_at: "2027-01-01T00:00:00Z" }, NOW)).toBe(
      "active",
    );
  });
});

describe("eligibilityBadgeClass", () => {
  it("client conflict (assignment allowed) is a warning, a veto is destructive", () => {
    expect(eligibilityBadgeClass({ assignment_allowed: true })).toContain("warning");
    expect(eligibilityBadgeClass({ assignment_allowed: false })).toContain("destructive");
  });
});

describe("canSubmitDeactivation", () => {
  it("needs at least three non-blank characters", () => {
    expect(canSubmitDeactivation("ab")).toBe(false);
    expect(canSubmitDeactivation("  ab  ")).toBe(false);
    expect(canSubmitDeactivation("abc")).toBe(true);
  });
});
