/**
 * Widoczność opcji „Usuń profil" w menu Więcej na profilu kandydata.
 *
 * Operacja jest nieodwracalna, więc lista rol, które ją widzą, jest tu
 * wyliczona WPROST — łącznie z rolami, które jej widzieć NIE mogą. Test na samą
 * ścieżkę pozytywną („admin widzi") przechodziłby również wtedy, gdyby opcja
 * była widoczna dla wszystkich.
 */
import { describe, expect, it } from "vitest";

import { canHardDeleteCandidate } from "@/lib/candidate-delete-access";
import type { User, UserRole } from "@/store/auth";

function withRole(role: UserRole, extra: UserRole[] = []): Pick<
  User,
  "role" | "roles"
> {
  return { role, roles: extra.length ? [role, ...extra] : [role] };
}

describe("canHardDeleteCandidate", () => {
  it("dopuszcza admina", () => {
    expect(canHardDeleteCandidate(withRole("admin"))).toBe(true);
  });

  it.each<UserRole>([
    // `delivery_lead` NIE jest tu przypadkiem hipotetycznym: do 2026-08
    // endpoint chronił `DeliveryLeadPlus`, więc ta rola usuwać mogła. Ticket to
    // zawęża i bez tego przypadku nic by zawężenia nie pilnowało.
    "delivery_lead",
    "head_of_recruitment",
    "tac",
    "recruiter",
    "sourcer",
    "finance",
    "user",
  ])("odmawia roli %s", (role) => {
    expect(canHardDeleteCandidate(withRole(role))).toBe(false);
  });

  it("odmawia, gdy nie ma zalogowanego użytkownika", () => {
    expect(canHardDeleteCandidate(null)).toBe(false);
    expect(canHardDeleteCandidate(undefined)).toBe(false);
  });

  it("dopuszcza admina przypisanego jako rola dodatkowa", () => {
    // Konta multi-role trzymają uprawnienie w `roles[]`, nie tylko w `role` —
    // gate czytający wyłącznie `role` odmówiłby adminowi z rolą główną DL.
    expect(canHardDeleteCandidate({ role: "delivery_lead", roles: ["admin"] })).toBe(
      true,
    );
  });

  it("odmawia, gdy `roles` zawiera same nieuprawnione wartości", () => {
    expect(
      canHardDeleteCandidate({
        role: "recruiter",
        roles: ["recruiter", "sourcer"],
      }),
    ).toBe(false);
  });
});
