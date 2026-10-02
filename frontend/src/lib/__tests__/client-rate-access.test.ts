import { describe, expect, it } from "vitest";

import { canViewClientRate, canWriteClientRate } from "@/lib/client-rate-access";
import type { UserRole } from "@/store/auth";

import { accessSnapshot } from "./fixtures/access-snapshot";

const ALL_ROLES: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "sourcer",
  "user",
  "trainee",
];

// Reguły zapasowe — gdy odpowiedź serwera nie niesie flag stawki do klienta.
describe("stawka do klienta — reguły zapasowe", () => {
  it("odczyt zostaje przy roli (lustro CLIENT_RATE_VIEW_ROLES)", () => {
    expect(ALL_ROLES.filter((role) => canViewClientRate({ role })).sort()).toEqual(
      [
        "admin",
        "delivery_lead",
        "finance",
        "head_of_recruitment",
        "talent_community_manager",
      ].sort(),
    );
    // Uprawnienie do rekrutacji nie otwiera odczytu — ten jest listą ról.
    expect(
      canViewClientRate(accessSnapshot("recruiter", { grant: ["recruitment_manage"] })),
    ).toBe(false);
    expect(canViewClientRate(null)).toBe(false);
  });

  it("zapis: domyślnie admin i Delivery Lead", () => {
    expect(ALL_ROLES.filter((role) => canWriteClientRate({ role })).sort()).toEqual(
      ["admin", "delivery_lead"].sort(),
    );
    expect(canWriteClientRate(null)).toBe(false);
  });

  it("zapis idzie za uprawnieniem „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”", () => {
    expect(
      canWriteClientRate(accessSnapshot("recruiter", { grant: ["recruitment_manage"] })),
    ).toBe(true);
    expect(
      canWriteClientRate(accessSnapshot("delivery_lead", { revoke: ["recruitment_manage"] })),
    ).toBe(false);
    // TAC ma pełną edycję rekrutacji z tytułu roli, ale stawki do klienta nie wpisuje.
    expect(canWriteClientRate(accessSnapshot("tac"))).toBe(false);
  });
});
