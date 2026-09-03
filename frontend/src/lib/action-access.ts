import type { UserRole } from "@/store/auth";

export type ProductAction = "b2b_contract_generator";
export type ActionAccess = "none" | "view" | "generate" | "manage";
export type UserActionOverrideAccess = ActionAccess | "inherit";

export const PRODUCT_ACTIONS: readonly ProductAction[] = [
  "b2b_contract_generator",
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
  admin: { b2b_contract_generator: "manage" },
  finance: { b2b_contract_generator: "manage" },
  head_of_recruitment: { b2b_contract_generator: "manage" },
  delivery_lead: { b2b_contract_generator: "manage" },
  talent_community_manager: { b2b_contract_generator: "view" },
  tac: { b2b_contract_generator: "manage" },
  recruiter: { b2b_contract_generator: "manage" },
  sourcer: { b2b_contract_generator: "manage" },
  user: { b2b_contract_generator: "view" },
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
