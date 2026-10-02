import { describe, expect, it } from "vitest";

import { canExtendContract } from "@/components/client-profile/actions/ExtendContractMenu";
import {
  canCloseJobAsLost,
  canManageAssignedClient,
  canManageClientContracts,
  canManageClientDelivery,
  canMoveInPipeline,
} from "@/components/client-profile/permissions";
import { accessSnapshot } from "@/lib/__tests__/fixtures/access-snapshot";
import type { User, UserRole } from "@/store/auth";

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

/**
 * Profil bez kompletu uprawnień z serwera (stary cache): liczy się
 * z DOMYŚLNYCH uprawnień roli, czyli ze stanu startowego ekranu Osoby i role.
 */
function user(role: User["role"], financeClientIds: number[] = []): User {
  return {
    id: 1,
    email: "u@example.com",
    name: "U",
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    data_scope:
      role === "delivery_lead"
        ? {
            kind: "delivery_clients",
            user_id: 1,
            allowed_client_ids: financeClientIds,
            finance_client_ids: financeClientIds,
            allowed_tac_user_ids: [],
            allowed_operator_user_ids: [],
            allowed_client_tac_pairs: [],
          }
        : undefined,
  } as User;
}

const defaultHolders = (gate: (account: User) => boolean) =>
  ALL_ROLES.filter((role) => gate(user(role))).sort();

describe("Przedłuż na profilu klienta (audyt W2)", () => {
  it("domyślnie admin, Delivery Lead i Finanse; tylko kontrakt „Kończący się”", () => {
    expect(canExtendContract(user("admin"), "ending")).toBe(true);
    expect(canExtendContract(user("delivery_lead"), "ending")).toBe(true);
    // Od 0410 Finanse mają „Kontrakty i zamówienia: tworzenie i edycja”.
    expect(canExtendContract(user("finance"), "ending")).toBe(true);
    // TCM zmienia status, ale kontraktów nie przedłuża — przycisku nie ma.
    expect(canExtendContract(user("talent_community_manager"), "ending")).toBe(false);
    // Aktywny bez daty końca nie ma czego przedłużać.
    expect(canExtendContract(user("admin"), "active")).toBe(false);
    expect(canExtendContract(user("admin"), null)).toBe(false);
  });

  it("idzie za uprawnieniem: nadane TCM — jest, wyłączone Delivery Leadowi — nie ma", () => {
    expect(
      canExtendContract(
        accessSnapshot("talent_community_manager", { grant: ["contracts_orders_edit"] }),
        "ending",
      ),
    ).toBe(true);
    expect(
      canExtendContract(
        accessSnapshot("delivery_lead", { revoke: ["contracts_orders_edit"] }),
        "ending",
      ),
    ).toBe(false);
    // Edycja klientów to inne uprawnienie — samo nie przedłuża kontraktów.
    expect(
      canExtendContract(accessSnapshot("recruiter", { grant: ["clients_edit"] }), "ending"),
    ).toBe(false);
  });

  it("canManageClientContracts: sufit sekcji Delivery zostaje", () => {
    expect(defaultHolders(canManageClientContracts)).toEqual(
      ["admin", "delivery_lead", "finance"].sort(),
    );
    expect(
      canManageClientContracts(
        accessSnapshot("delivery_lead", { sectionCaps: { delivery: "read" } }),
      ),
    ).toBe(false);
    expect(canManageClientContracts(null)).toBe(false);
  });
});

describe("Umowy wykonawcze: „Kontrakty i zamówienia” u klienta z przypisania (audyt S11)", () => {
  it("DL tylko u klienta z własnego portfela, admin wszędzie", () => {
    expect(canManageAssignedClient(user("admin"), 5)).toBe(true);
    expect(canManageAssignedClient(user("delivery_lead", [5]), 5)).toBe(true);
    expect(canManageAssignedClient(user("delivery_lead", [6]), 5)).toBe(false);
    expect(canManageAssignedClient(user("recruiter"), 5)).toBe(false);
    expect(canManageAssignedClient(user("talent_community_manager"), 5)).toBe(false);
  });

  it("pozostałych posiadaczy przypisanie nie dotyczy: Finanse i osoba z nadanym uprawnieniem", () => {
    expect(canManageAssignedClient(user("finance"), 5)).toBe(true);
    const tcm = accessSnapshot("talent_community_manager", {
      grant: ["contracts_orders_edit"],
    });
    expect(canManageAssignedClient(tcm, 5)).toBe(true);
    expect(canManageAssignedClient(tcm, 999)).toBe(true);
  });

  it("Delivery Lead z wyłączonym uprawnieniem nie edytuje nawet u swojego klienta", () => {
    const lead = accessSnapshot("delivery_lead", {
      revoke: ["contracts_orders_edit"],
      assignedClientIds: [5],
    });
    expect(canManageAssignedClient(lead, 5)).toBe(false);
  });

  it("portfel wiąże także hybrydę z rolą Delivery Leada", () => {
    const hybrid = accessSnapshot("head_of_recruitment", {
      roles: ["delivery_lead"],
      assignedClientIds: [5],
    });
    expect(canManageAssignedClient(hybrid, 5)).toBe(true);
    expect(canManageAssignedClient(hybrid, 6)).toBe(false);
  });
});

describe("canManageClientDelivery — „Klienci: dodawanie i edycja”", () => {
  it("domyślnie admin i Delivery Lead, nie rekruter ani Finanse", () => {
    expect(defaultHolders(canManageClientDelivery)).toEqual(
      ["admin", "delivery_lead"].sort(),
    );
    expect(canManageClientDelivery(user("recruiter"))).toBe(false);
    expect(canManageClientDelivery(user("finance"))).toBe(false);
    expect(canManageClientDelivery(null)).toBe(false);
  });

  it("rekruter z nadanym uprawnieniem edytuje, Delivery Lead z wyłączonym — nie", () => {
    expect(
      canManageClientDelivery(accessSnapshot("recruiter", { grant: ["clients_edit"] })),
    ).toBe(true);
    expect(
      canManageClientDelivery(accessSnapshot("delivery_lead", { revoke: ["clients_edit"] })),
    ).toBe(false);
    // Finanse zakładają kontrakty, ale to nie daje edycji klientów.
    expect(canManageClientDelivery(accessSnapshot("finance"))).toBe(false);
  });

  it("sufit sekcji Delivery zostaje (stary wyjątek osoby)", () => {
    expect(
      canManageClientDelivery(
        accessSnapshot("delivery_lead", { sectionCaps: { delivery: "read" } }),
      ),
    ).toBe(false);
  });
});

describe("canCloseJobAsLost — „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”", () => {
  it("domyślnie admin i Delivery Lead", () => {
    expect(defaultHolders(canCloseJobAsLost)).toEqual(["admin", "delivery_lead"].sort());
  });

  it("rekruter z nadanym uprawnieniem zamyka, Delivery Lead z wyłączonym — nie; TAC nigdy", () => {
    expect(
      canCloseJobAsLost(accessSnapshot("recruiter", { grant: ["recruitment_manage"] })),
    ).toBe(true);
    expect(
      canCloseJobAsLost(accessSnapshot("delivery_lead", { revoke: ["recruitment_manage"] })),
    ).toBe(false);
    // Rola TAC daje pełną edycję rekrutacji, ale nie jej zamknięcie.
    expect(canCloseJobAsLost(accessSnapshot("tac"))).toBe(false);
  });

  it("wymaga zapisu w sekcji Pipeline", () => {
    expect(
      canCloseJobAsLost(
        accessSnapshot("delivery_lead", { sectionCaps: { pipeline: "read" } }),
      ),
    ).toBe(false);
  });
});

describe("canMoveInPipeline — zostaje przy roli (RecruiterPlus)", () => {
  it("każda rola operacyjna z zapisem Pipeline; viewer i praktykant nie", () => {
    expect(defaultHolders(canMoveInPipeline)).toEqual(
      [
        "admin",
        "delivery_lead",
        "finance",
        "head_of_recruitment",
        "recruiter",
        "sourcer",
        "tac",
        "talent_community_manager",
      ].sort(),
    );
    expect(
      canMoveInPipeline(accessSnapshot("recruiter", { sectionCaps: { pipeline: "read" } })),
    ).toBe(false);
    // Uprawnienie do rekrutacji nie zastępuje roli operacyjnej.
    expect(canMoveInPipeline(accessSnapshot("user"))).toBe(false);
  });
});
