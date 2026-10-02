/**
 * Dane do testów ekranu „Osoby i role” w kształcie kontraktu §7
 * (`docs/permissions-nine-switches-contract.md`). `named` liczy się tu tak,
 * jak liczy je serwer: wiersz zapisany + to, co z niego wynika.
 */
import type {
  AdminPermissionsSnapshot,
  AdminRolePermissions,
  AdminUserPermissions,
  AdminUserPermissionsResponse,
} from "@/lib/admin-permissions";
import {
  PERMISSIONS,
  PERMISSION_GROUPS,
  PERMISSION_KEYS,
  closePermissions,
  deriveSections,
  impliedBy,
  type Permission,
} from "@/lib/permissions";
import type { UserRole } from "@/store/auth";

export function roleEntry(
  role: UserRole,
  granted: readonly Permission[],
  extra: Partial<AdminRolePermissions> = {},
): AdminRolePermissions {
  const effective = closePermissions(granted);
  const sections = deriveSections(effective);
  return {
    role,
    users_count: 0,
    grantable: !["admin", "user", "trainee"].includes(role),
    locked: role === "admin",
    permissions: {
      sourcing: "write",
      pipeline: "write",
      delivery: sections.delivery,
      insights: "read",
      finance: sections.finance,
      system_admin: role === "admin" ? "write" : "none",
    },
    action_permissions: { b2b_contract_generator: "manage" },
    named: Object.fromEntries(
      PERMISSION_KEYS.map((key) => [
        key,
        {
          granted: granted.includes(key),
          effective: effective.has(key),
          implied_by: impliedBy(key, granted),
        },
      ]),
    ),
    ...extra,
  };
}

/** Domyślne uprawnienia ról z katalogu — stan świeżej instalacji. */
function defaultGrants(role: UserRole): Permission[] {
  return PERMISSIONS.filter((permission) =>
    permission.default_roles.includes(role),
  ).map((permission) => permission.key);
}

const ROLE_HEADCOUNT: Partial<Record<UserRole, number>> = {
  finance: 1,
  head_of_recruitment: 2,
  delivery_lead: 7,
  talent_community_manager: 6,
  tac: 2,
  recruiter: 8,
  sourcer: 3,
};

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

export function permissionsSnapshot(
  overrides: Partial<AdminPermissionsSnapshot> = {},
): AdminPermissionsSnapshot {
  return {
    revision: 12,
    derived_sections: ["delivery", "finance"],
    permission_groups: PERMISSION_GROUPS.map((group) => ({
      key: group.key,
      label: group.label,
      permissions: [...group.permissions],
    })),
    permissions: PERMISSIONS.map((permission) => ({
      key: permission.key,
      label: permission.label,
      group: permission.group,
      requires: [...permission.requires],
      default_roles: [...permission.default_roles],
    })),
    roles: ALL_ROLES.map((role) =>
      roleEntry(role, role === "admin" ? [...PERMISSION_KEYS] : defaultGrants(role), {
        users_count: ROLE_HEADCOUNT[role] ?? 0,
      }),
    ),
    ...overrides,
  };
}

export function userPermissionsResponse(
  user: Partial<AdminUserPermissions> = {},
  revision = 12,
): AdminUserPermissionsResponse {
  const roles = user.roles ?? ["talent_community_manager"];
  const rolePermissions =
    user.role_permissions ??
    [...closePermissions(roles.flatMap((role) => defaultGrants(role)))];
  const grants = user.grants ?? [];
  return {
    revision,
    user: {
      user_id: 90,
      name: "Celina Wzorcowa",
      role: roles[0],
      roles,
      locked: false,
      grantable: true,
      role_permissions: rolePermissions,
      grants,
      restrictions: [],
      effective: [...closePermissions([...rolePermissions, ...grants])],
      legacy_section_caps: {},
      ...user,
    },
  };
}
