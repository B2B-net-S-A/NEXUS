import { describe, expect, it } from "vitest";

import { normalizeRole, normalizeRoles } from "@/lib/role-normalize";

// Role `tac` i `sourcer` połączono z `recruiter` (02.10.2026). Token i profil
// zapisane w przeglądarce przed wdrożeniem mogą je jeszcze nieść.
describe("normalizeRole", () => {
  it("zamienia `tac` i `sourcer` na `recruiter`", () => {
    expect(normalizeRole("tac")).toBe("recruiter");
    expect(normalizeRole("sourcer")).toBe("recruiter");
  });

  it("pozostałe role zostawia bez zmian", () => {
    for (const role of [
      "admin",
      "finance",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "recruiter",
      "user",
      "trainee",
    ]) {
      expect(normalizeRole(role)).toBe(role);
    }
  });
});

describe("normalizeRoles", () => {
  it("usuwa powtórzenia powstałe po zamianie i zachowuje kolejność", () => {
    expect(normalizeRoles(["tac", "recruiter", "sourcer"])).toEqual(["recruiter"]);
    expect(normalizeRoles(["delivery_lead", "tac"])).toEqual([
      "delivery_lead",
      "recruiter",
    ]);
    expect(normalizeRoles(["sourcer", "delivery_lead", "tac"])).toEqual([
      "recruiter",
      "delivery_lead",
    ]);
  });

  it("pusta lista zostaje pusta", () => {
    expect(normalizeRoles([])).toEqual([]);
  });
});
