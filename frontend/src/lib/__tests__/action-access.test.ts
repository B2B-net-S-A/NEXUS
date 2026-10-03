import { describe, expect, it } from "vitest";

import {
  actionAccessForRoles,
  actionAccessForUser,
  hasActionAccess,
} from "@/lib/action-access";
import { hasPermission } from "@/lib/permissions";
import type { UserRole } from "@/store/auth";

import { accessSnapshot } from "./fixtures/access-snapshot";

const ACTION = "b2b_contract_generator" as const;

describe("action access", () => {
  it("preserves existing operators and gives TCM the full generator (U1, 22.09)", () => {
    expect(actionAccessForRoles(["recruiter"], ACTION)).toBe("manage");
    expect(actionAccessForRoles(["delivery_lead"], ACTION)).toBe("manage");
    expect(
      actionAccessForRoles(["talent_community_manager"], ACTION),
    ).toBe("manage");
    expect(actionAccessForRoles(["user"], ACTION)).toBe("view");
  });

  it("uses the strongest role in a multi-role account", () => {
    expect(actionAccessForRoles(["user", "recruiter"], ACTION)).toBe("manage");
  });

  it("treats an authoritative per-user snapshot as a replacement", () => {
    const user = {
      role: "talent_community_manager" as const,
      roles: ["talent_community_manager" as const],
      effective_action_access: { b2b_contract_generator: "generate" as const },
    };

    expect(actionAccessForUser(user, ACTION)).toBe("generate");
    expect(hasActionAccess(user, ACTION, "view")).toBe(true);
    expect(hasActionAccess(user, ACTION, "generate")).toBe(true);
    expect(hasActionAccess(user, ACTION, "manage")).toBe(false);
  });

  it("fails closed when the authoritative snapshot omits the action", () => {
    expect(
      actionAccessForUser(
        {
          role: "recruiter",
          roles: ["recruiter"],
          effective_action_access: {},
        },
        ACTION,
      ),
    ).toBe("none");
  });
});

// Podpis B2B jest jednym z dziewięciu uprawnień z ekranu Osoby i role. Ma jedno
// źródło — `lib/permissions.ts` — a ten moduł odpowiada tym samym, żeby dwa
// pytania o to samo konto nie dawały dwóch odpowiedzi.
describe("podpis B2B: action-access zgadza się z lib/permissions", () => {
  const SIGNATURE = "b2b_signature_confirmation" as const;
  const ROLES: UserRole[] = [
    "admin",
    "finance",
    "head_of_recruitment",
    "delivery_lead",
    "talent_community_manager",
    "recruiter",
    "user",
    "trainee",
  ];

  const agree = (user: Parameters<typeof actionAccessForUser>[0]) => {
    const held = hasPermission(user, SIGNATURE);
    expect(actionAccessForUser(user, SIGNATURE)).toBe(held ? "manage" : "none");
    expect(hasActionAccess(user, SIGNATURE, "manage")).toBe(held);
    return held;
  };

  it("domyślnie: admin, Delivery Lead i TCM", () => {
    expect(ROLES.filter((role) => agree({ role })).sort()).toEqual(
      ["admin", "delivery_lead", "talent_community_manager"].sort(),
    );
    expect(ROLES.filter((role) => agree(accessSnapshot(role))).sort()).toEqual(
      ["admin", "delivery_lead", "talent_community_manager"].sort(),
    );
  });

  it("profil sprzed 0410 z „manage” u rekrutera (dawnego TAC-a) nie daje podpisu w żadnym z modułów", () => {
    // Stary komplet niósł TAC-owi podpis, którego zakres klienta i tak nigdy
    // nie przepuszczał; rola TAC jest dziś rekruterem (02.10.2026). Bez klucza
    // `delivery_view` profil jest nieaktualny, więc liczą się domyślne
    // uprawnienia roli.
    const staleTac = {
      role: "recruiter" as const,
      roles: ["recruiter" as const],
      effective_action_access: {
        b2b_contract_generator: "manage" as const,
        b2b_signature_confirmation: "manage" as const,
      },
    };
    expect(agree(staleTac)).toBe(false);
    // Generator czyta ten sam stary komplet jak dotąd.
    expect(actionAccessForUser(staleTac, ACTION)).toBe("manage");
  });

  it("nadane rekruterowi i wyłączone Delivery Leadowi — oba moduły widzą to samo", () => {
    expect(agree(accessSnapshot("recruiter", { grant: [SIGNATURE] }))).toBe(true);
    expect(agree(accessSnapshot("delivery_lead", { revoke: [SIGNATURE] }))).toBe(false);
  });

  it("uprawnienie jest tak/nie: poziom inny niż „manage” go nie nadaje", () => {
    const partial = {
      role: "recruiter" as const,
      effective_action_access: {
        ...accessSnapshot("recruiter").effective_action_access,
        b2b_signature_confirmation: "view" as const,
      },
    };
    expect(agree(partial)).toBe(false);
    expect(hasActionAccess(partial, SIGNATURE, "view")).toBe(false);
  });
});
