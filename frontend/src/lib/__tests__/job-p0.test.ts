import { describe, expect, it } from "vitest";

import {
  isP0Active,
  isP0Overdue,
  p0OverdueLabel,
  p0Remaining,
  p0UntilLabel,
  validateP0Reason,
} from "@/lib/job-p0";

const NOW = new Date("2026-10-27T09:09:00Z"); // wtorek 10:09 w Warszawie

describe("isP0Active", () => {
  it("obowiązuje na otwartej rekrutacji z terminem — także po terminie (06.11.2026)", () => {
    expect(isP0Active({ is_p0: true, p0_until: "2026-10-28T09:09:00Z", status: "published" })).toBe(true);
    expect(isP0Active({ is_p0: true, p0_until: "2026-10-27T09:08:00Z", status: "published" })).toBe(true);
  });
  it("bez terminu, na zamkniętej i przy is_p0=false — nie", () => {
    expect(isP0Active({ p0_until: null })).toBe(false);
    expect(isP0Active({ p0_until: "nie-data" })).toBe(false);
    expect(isP0Active({ p0_until: "2026-10-28T09:09:00Z", status: "closed" })).toBe(false);
    expect(isP0Active({ is_p0: false, p0_until: "2026-10-28T09:09:00Z" })).toBe(false);
    expect(isP0Active(null)).toBe(false);
  });
});

describe("isP0Overdue", () => {
  it("termin minął, a P0 trwa — czeka na decyzję", () => {
    expect(isP0Overdue({ is_p0: true, p0_until: "2026-10-27T09:08:00Z" }, NOW)).toBe(true);
    expect(isP0Overdue({ is_p0: true, p0_until: "2026-10-27T09:09:00Z" }, NOW)).toBe(true);
  });
  it("przed terminem, bez P0 i na zamkniętej — nie", () => {
    expect(isP0Overdue({ is_p0: true, p0_until: "2026-10-27T09:10:00Z" }, NOW)).toBe(false);
    expect(isP0Overdue({ is_p0: false, p0_until: "2026-10-27T09:08:00Z" }, NOW)).toBe(false);
    expect(isP0Overdue({ p0_until: "2026-10-27T09:08:00Z", status: "closed" }, NOW)).toBe(false);
    expect(isP0Overdue(null, NOW)).toBe(false);
  });
});

describe("p0OverdueLabel", () => {
  it("minuty, godziny i dni po terminie", () => {
    expect(p0OverdueLabel("2026-10-27T08:14:00Z", NOW)).toBe("minęło 55 min");
    expect(p0OverdueLabel("2026-10-27T06:09:00Z", NOW)).toBe("minęło 3 h");
    expect(p0OverdueLabel("2026-10-25T09:09:00Z", NOW)).toBe("minęło 2 dni");
    expect(p0OverdueLabel("2026-10-27T09:09:00Z", NOW)).toBe("minęło 0 min");
  });
});

describe("p0Remaining", () => {
  it("minuty, godziny i dni", () => {
    expect(p0Remaining("2026-10-27T09:54:00Z", NOW)).toBe("45 min");
    expect(p0Remaining("2026-10-28T08:09:00Z", NOW)).toBe("23 h");
    expect(p0Remaining("2026-10-30T17:00:00Z", NOW)).toBe("3 dni 7 h");
    expect(p0Remaining("2026-10-29T09:09:00Z", NOW)).toBe("2 dni");
  });
  it("po terminie i bez terminu — null", () => {
    expect(p0Remaining("2026-10-27T09:09:00Z", NOW)).toBeNull();
    expect(p0Remaining(null, NOW)).toBeNull();
    expect(p0Remaining("nie-data", NOW)).toBeNull();
  });
});

describe("p0UntilLabel", () => {
  it("dziś, jutro i dalszy dzień w czasie warszawskim", () => {
    expect(p0UntilLabel("2026-10-27T15:00:00Z", NOW)).toBe("dziś 16:00");
    expect(p0UntilLabel("2026-10-28T09:09:00Z", NOW)).toBe("jutro 10:09");
    expect(p0UntilLabel("2026-10-30T17:00:00Z", NOW)).toMatch(/30\.10, 18:00$/);
  });
});

describe("validateP0Reason", () => {
  it("wymaga powodu i przycina białe znaki", () => {
    expect(validateP0Reason("  ").error).not.toBeNull();
    expect(validateP0Reason("ok").error).not.toBeNull();
    expect(validateP0Reason("  Klient   chce\n2 CV ")).toEqual({ reason: "Klient chce 2 CV", error: null });
  });
  it("odmawia powyżej 300 znaków", () => {
    expect(validateP0Reason("x".repeat(301)).error).toMatch(/300/);
  });
});
