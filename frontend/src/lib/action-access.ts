import { hasPermission, isPermission } from "@/lib/permissions";
import type { UserRole } from "@/store/auth";

/**
 * Akcje z poziomami dostępu. `b2b_contract_generator` to drabinka podgląd /
 * generowanie / zarządzanie. `b2b_signature_confirmation` jest jednym
 * z dziewięciu uprawnień z ekranu Osoby i role — zostaje tu dla starego panelu
 * i typów API, ale o to, czy konto je MA, pytaj `hasPermission`
 * (`lib/permissions.ts`); `actionAccessForUser` odpowiada tym samym.
 */
export type ProductAction =
  "b2b_contract_generator" | "b2b_signature_confirmation";
export type ActionAccess = "none" | "view" | "generate" | "manage";
export type UserActionOverrideAccess = ActionAccess | "inherit";

export const PRODUCT_ACTIONS: readonly ProductAction[] = [
  "b2b_contract_generator",
  "b2b_signature_confirmation",
];

export const ACTION_ACCESS_RANK: Record<ActionAccess, number> = {
  none: 0,
  view: 1,
  generate: 2,
  manage: 3,
};

export const ROLE_ACTION_ACCESS: Record<
  UserRole,
  Record<ProductAction, ActionAccess>
> = {
  admin: {
    b2b_contract_generator: "manage",
    b2b_signature_confirmation: "manage",
  },
  finance: {
    b2b_contract_generator: "manage",
    b2b_signature_confirmation: "none",
  },
  head_of_recruitment: {
    b2b_contract_generator: "manage",
    b2b_signature_confirmation: "none",
  },
  delivery_lead: {
    b2b_contract_generator: "manage",
    b2b_signature_confirmation: "manage",
  },
  // Decyzja Artura 22.09.2026 (audyt ról U1): pełny generator B2B dla TCM —
  // zapisane w kodzie, nie tylko w panelu RBAC produkcji.
  talent_community_manager: {
    b2b_contract_generator: "manage",
    b2b_signature_confirmation: "manage",
  },
  recruiter: {
    b2b_contract_generator: "manage",
    b2b_signature_confirmation: "none",
  },
  user: { b2b_contract_generator: "view", b2b_signature_confirmation: "none" },
  // Praktykant (0374) nie ma dostępu do generatorów — jeden ekran telefonów.
  trainee: { b2b_contract_generator: "none", b2b_signature_confirmation: "none" },
};

export interface ActionUser {
  role: UserRole;
  roles?: readonly UserRole[];
  effective_action_access?: Partial<Record<ProductAction, ActionAccess>>;
}

export function actionAccessForRoles(
  roles: Iterable<UserRole>,
  action: ProductAction,
): ActionAccess {
  let granted: ActionAccess = "none";
  for (const role of roles) {
    const candidate = ROLE_ACTION_ACCESS[role]?.[action] ?? "none";
    if (ACTION_ACCESS_RANK[candidate] > ACTION_ACCESS_RANK[granted]) {
      granted = candidate;
    }
  }
  return granted;
}

export function actionAccessForUser(
  user: ActionUser | null | undefined,
  action: ProductAction,
): ActionAccess {
  if (!user) return "none";
  // Podpis B2B jest jednym z dziewięciu uprawnień z ekranu Osoby i role
  // (tak/nie), a te mają JEDNO źródło: `lib/permissions.ts`. Dwie kopie
  // rozjeżdżały się na profilu sprzed 0410 — stary komplet niósł TAC-owi
  // „manage”, którego katalog już nie daje.
  if (isPermission(action)) {
    return hasPermission(user, action) ? "manage" : "none";
  }
  if (user.effective_action_access) {
    const effective = user.effective_action_access[action];
    return effective && effective in ACTION_ACCESS_RANK ? effective : "none";
  }
  return actionAccessForRoles(
    new Set<UserRole>([user.role, ...(user.roles ?? [])]),
    action,
  );
}

export function hasActionAccess(
  user: ActionUser | null | undefined,
  action: ProductAction,
  required: Exclude<ActionAccess, "none"> = "view",
): boolean {
  return (
    ACTION_ACCESS_RANK[actionAccessForUser(user, action)] >=
    ACTION_ACCESS_RANK[required]
  );
}
