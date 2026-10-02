import { describe, expect, it } from "vitest";

import {
  PERMISSIONS,
  PERMISSION_GROUPS,
  PERMISSION_KEYS,
  closePermissions,
  defaultPermissionsForRoles,
  deriveSections,
  hasAnyPermission,
  hasPermission,
  impliedBy,
  isDeliveryLeadGoverned,
  permissionLabel,
  permissionsOfUser,
  type Permission,
} from "@/lib/permissions";
import { ALL_USER_ROLES, ROLE_SECTION_ACCESS } from "@/lib/section-access";
import { ROLE_ACTION_ACCESS } from "@/lib/action-access";
import type { UserRole } from "@/store/auth";

// Macierz z planu (decyzje 02.10.2026) — ta sama, którą asertuje backend
// w `test_permission_catalog.py`.
const EXPECTED_DEFAULTS: Record<UserRole, Permission[]> = {
  admin: [...PERMISSION_KEYS],
  finance: [
    "delivery_view",
    "contracts_orders_edit",
    "amounts_view",
    "amounts_edit",
    "finance_module",
  ],
  head_of_recruitment: [],
  delivery_lead: [
    "delivery_view",
    "clients_edit",
    "contracts_orders_edit",
    "contract_status",
    "b2b_signature_confirmation",
    "recruitment_manage",
    "amounts_view",
  ],
  talent_community_manager: [
    "delivery_view",
    "contract_status",
    "b2b_signature_confirmation",
  ],
  tac: [],
  recruiter: [],
  sourcer: [],
  user: [],
  trainee: [],
};

const sorted = (values: Iterable<string>) => [...values].sort();

describe("katalog uprawnień", () => {
  it("ma dziewięć pozycji w trzech grupach, w kolejności ekranu", () => {
    expect(PERMISSIONS.map((permission) => permission.label)).toEqual([
      "Klienci, kontrakty i zamówienia: podgląd",
      "Klienci: dodawanie i edycja",
      "Kontrakty i zamówienia: tworzenie i edycja",
      "Zakończenie współpracy, zmiana statusu kontraktu",
      "Umowy B2B: oznaczanie jako podpisane",
      "Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta",
      "Stawki i kwoty: podgląd",
      "Stawki i kwoty: zmiana",
      "Moduł Finanse",
    ]);
    expect(
      PERMISSION_GROUPS.map((group) => [group.label, group.permissions.length]),
    ).toEqual([
      ["Klienci i kontrakty", 5],
      ["Rekrutacje", 1],
      ["Pieniądze", 3],
    ]);
    expect(permissionLabel("finance_module")).toBe("Moduł Finanse");
  });

  it.each(ALL_USER_ROLES)("domyślne uprawnienia roli %s", (role) => {
    expect(sorted(defaultPermissionsForRoles([role]))).toEqual(
      sorted(EXPECTED_DEFAULTS[role]),
    );
  });

  it("edycja pociąga podgląd, a zmiana kwot — podgląd kwot", () => {
    expect(sorted(closePermissions(["clients_edit"]))).toEqual(
      sorted(["clients_edit", "delivery_view"]),
    );
    expect(sorted(closePermissions(["amounts_edit"]))).toEqual(
      sorted(["amounts_edit", "amounts_view", "delivery_view"]),
    );
    expect(sorted(closePermissions(["recruitment_manage"]))).toEqual([
      "recruitment_manage",
    ]);
    expect(impliedBy("delivery_view", ["clients_edit", "amounts_edit"])).toEqual([
      "clients_edit",
      "amounts_edit",
    ]);
    expect(impliedBy("clients_edit", ["delivery_view"])).toEqual([]);
  });

  it("sekcje Delivery i Finanse wynikają z uprawnień", () => {
    expect(deriveSections([])).toEqual({ delivery: "none", finance: "none" });
    expect(deriveSections(["delivery_view"])).toEqual({
      delivery: "read",
      finance: "none",
    });
    expect(deriveSections(["delivery_view", "contract_status"])).toEqual({
      delivery: "write",
      finance: "none",
    });
    expect(
      deriveSections(["delivery_view", "amounts_view", "finance_module"]),
    ).toEqual({ delivery: "read", finance: "write" });
  });

  it.each(ALL_USER_ROLES)(
    "macierz startowa sekcji roli %s zgadza się z uprawnieniami",
    (role) => {
      const derived = deriveSections(defaultPermissionsForRoles([role]));
      expect(ROLE_SECTION_ACCESS[role].delivery).toBe(derived.delivery);
      expect(ROLE_SECTION_ACCESS[role].finance).toBe(derived.finance);
    },
  );

  it.each(ALL_USER_ROLES)(
    "macierz startowa akcji roli %s zgadza się z podpisem B2B w katalogu",
    (role) => {
      expect(ROLE_ACTION_ACCESS[role].b2b_signature_confirmation).toBe(
        defaultPermissionsForRoles([role]).has("b2b_signature_confirmation")
          ? "manage"
          : "none",
      );
    },
  );
});

describe("uprawnienia konta", () => {
  it("czyta komplet z backendu, gdy profil go niesie", () => {
    const sandra = {
      role: "talent_community_manager" as const,
      effective_action_access: {
        b2b_contract_generator: "manage",
        delivery_view: "manage",
        contract_status: "manage",
        contracts_orders_edit: "manage",
        amounts_view: "none",
      },
    };

    expect(hasPermission(sandra, "contracts_orders_edit")).toBe(true);
    expect(hasPermission(sandra, "amounts_view")).toBe(false);
    // Brak klucza w komplecie z backendu = brak uprawnienia.
    expect(hasPermission(sandra, "b2b_signature_confirmation")).toBe(false);
    expect(hasAnyPermission(sandra, "amounts_edit", "contract_status")).toBe(true);
    expect(sorted(permissionsOfUser(sandra))).toEqual(
      sorted(["delivery_view", "contract_status", "contracts_orders_edit"]),
    );
  });

  it("tylko „manage” nadaje uprawnienie", () => {
    const user = {
      role: "recruiter" as const,
      effective_action_access: { delivery_view: "view" },
    };
    expect(hasPermission(user, "delivery_view")).toBe(false);
  });

  it("profil sprzed wdrożenia liczy z domyślnych uprawnień roli", () => {
    const stale = {
      role: "delivery_lead" as const,
      effective_action_access: { b2b_contract_generator: "manage" },
    };
    expect(hasPermission(stale, "clients_edit")).toBe(true);
    expect(hasPermission(stale, "finance_module")).toBe(false);

    expect(hasPermission({ role: "finance" }, "contracts_orders_edit")).toBe(true);
    expect(hasPermission({ role: "finance" }, "contract_status")).toBe(false);
    expect(hasPermission({ role: "recruiter" }, "delivery_view")).toBe(false);
  });

  it("konto wielorolowe bez kompletu z backendu ma sumę ról", () => {
    const hybrid = {
      role: "recruiter" as const,
      roles: ["recruiter", "talent_community_manager"] as const,
    };
    expect(hasPermission(hybrid, "contract_status")).toBe(true);
  });

  it("bez użytkownika nie ma uprawnień", () => {
    expect(hasPermission(null, "delivery_view")).toBe(false);
    expect(hasAnyPermission(undefined, "delivery_view")).toBe(false);
  });

  it("portfel Delivery Leada wyznacza zakres tylko kontom z tą rolą", () => {
    expect(isDeliveryLeadGoverned({ role: "delivery_lead" })).toBe(true);
    expect(
      isDeliveryLeadGoverned({
        role: "head_of_recruitment",
        roles: ["head_of_recruitment", "delivery_lead"],
      }),
    ).toBe(true);
    expect(
      isDeliveryLeadGoverned({ role: "admin", roles: ["admin", "delivery_lead"] }),
    ).toBe(false);
    expect(isDeliveryLeadGoverned({ role: "talent_community_manager" })).toBe(false);
    expect(isDeliveryLeadGoverned(null)).toBe(false);
  });
});
