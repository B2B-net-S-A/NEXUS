import type { UserRole } from "@/store/auth";
import type {
  ActionAccess,
  ProductAction,
  UserActionOverrideAccess,
} from "@/lib/action-access";

export type ProductSection =
  | "sourcing"
  | "pipeline"
  | "delivery"
  | "insights"
  | "finance"
  | "system_admin";

export type SectionAccess = "none" | "read" | "write";
export type UserSectionOverrideAccess = SectionAccess | "inherit";

export const PRODUCT_SECTIONS: readonly ProductSection[] = [
  "sourcing",
  "pipeline",
  "delivery",
  "insights",
  "finance",
  "system_admin",
];

export interface RoleSectionPermissions {
  role: UserRole;
  permissions: Record<ProductSection, SectionAccess>;
  action_permissions?: Record<ProductAction, ActionAccess>;
  locked?: boolean;
  locked_sections?: ProductSection[];
}

export interface SectionPermissionsResponse {
  revision: number;
  roles: RoleSectionPermissions[];
  actions?: ProductAction[];
}

export interface UserSectionPermissions {
  user_id: number;
  name: string;
  email: string;
  role: UserRole;
  roles?: UserRole[];
  is_active?: boolean;
  locked?: boolean;
  overrides: Partial<Record<ProductSection, SectionAccess>>;
  inherited_permissions?: Record<ProductSection, SectionAccess>;
  effective_permissions: Record<ProductSection, SectionAccess>;
  action_overrides?: Partial<Record<ProductAction, ActionAccess>>;
  inherited_action_permissions?: Record<ProductAction, ActionAccess>;
  effective_action_permissions?: Record<ProductAction, ActionAccess>;
  scope_summary?: string;
}

export interface UserSectionPermissionsResponse {
  revision: number;
  users: UserSectionPermissions[];
  total?: number;
}

export interface RoleSectionPermissionChange {
  role: UserRole;
  section: ProductSection;
  access: SectionAccess;
}

export interface UserSectionPermissionChange {
  section: ProductSection;
  access: UserSectionOverrideAccess;
}

export interface RoleActionPermissionChange {
  role: UserRole;
  action: ProductAction;
  access: ActionAccess;
}

export interface UserActionPermissionChange {
  action: ProductAction;
  access: UserActionOverrideAccess;
}

export interface SectionPermissionMutationResponse {
  revision: number;
  changed: boolean;
  invalidated_users: number;
}

export interface SectionUser {
  role: UserRole;
  roles?: readonly UserRole[];
  /**
   * Autorytatywny wynik polityki RBAC zwracany przez backend. Pole jest
   * opcjonalne wyłącznie na czas hydracji starszych sesji zapisanych w
   * localStorage; jeśli mapa istnieje, brak sekcji oznacza jawne `none`.
   */
  effective_section_access?: Partial<Record<ProductSection, SectionAccess>>;
}

export const ALL_USER_ROLES: readonly UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "sourcer",
  "user",
];

/**
 * Coarse product-section policy. Endpoint-specific capabilities remain the
 * final authority for actions inside an allowed section.
 *
 * Keep in parity with backend/app/api/section_access.py.
 */
export const ROLE_SECTION_ACCESS: Record<
  UserRole,
  Record<ProductSection, SectionAccess>
> = {
  admin: {
    sourcing: "write",
    pipeline: "write",
    delivery: "write",
    insights: "write",
    finance: "write",
    system_admin: "write",
  },
  finance: {
    sourcing: "write",
    pipeline: "write",
    delivery: "write",
    insights: "read",
    finance: "write",
    system_admin: "none",
  },
  head_of_recruitment: {
    sourcing: "write",
    pipeline: "write",
    delivery: "none",
    insights: "write",
    finance: "none",
    system_admin: "none",
  },
  delivery_lead: {
    sourcing: "write",
    pipeline: "write",
    delivery: "write",
    insights: "read",
    finance: "none",
    system_admin: "none",
  },
  talent_community_manager: {
    sourcing: "write",
    pipeline: "write",
    delivery: "read",
    insights: "read",
    finance: "none",
    system_admin: "none",
  },
  tac: {
    sourcing: "write",
    pipeline: "write",
    delivery: "none",
    insights: "read",
    finance: "none",
    system_admin: "none",
  },
  recruiter: {
    sourcing: "write",
    pipeline: "write",
    delivery: "none",
    insights: "read",
    finance: "none",
    system_admin: "none",
  },
  sourcer: {
    sourcing: "write",
    pipeline: "write",
    delivery: "none",
    insights: "read",
    finance: "none",
    system_admin: "none",
  },
  user: {
    sourcing: "read",
    pipeline: "read",
    delivery: "none",
    insights: "read",
    finance: "none",
    system_admin: "none",
  },
};

const ACCESS_RANK: Record<SectionAccess, number> = {
  none: 0,
  read: 1,
  write: 2,
};

export function sectionAccessForRoles(
  roles: Iterable<UserRole>,
  section: ProductSection,
): SectionAccess {
  let granted: SectionAccess = "none";
  for (const role of roles) {
    const candidate = ROLE_SECTION_ACCESS[role]?.[section] ?? "none";
    if (ACCESS_RANK[candidate] > ACCESS_RANK[granted]) granted = candidate;
  }
  return granted;
}

export function sectionAccessForUser(
  user: SectionUser | null | undefined,
  section: ProductSection,
): SectionAccess {
  if (!user) return "none";
  if (user.effective_section_access) {
    const effective = user.effective_section_access[section];
    return effective === "read" || effective === "write" ? effective : "none";
  }
  return sectionAccessForRoles(
    new Set<UserRole>([user.role, ...(user.roles ?? [])]),
    section,
  );
}

export function hasSectionAccess(
  user: SectionUser | null | undefined,
  section: ProductSection,
  required: Exclude<SectionAccess, "none"> = "read",
): boolean {
  return (
    ACCESS_RANK[sectionAccessForUser(user, section)] >= ACCESS_RANK[required]
  );
}

/**
 * UI guard for actions that mutate a product section. Impersonation is a
 * read-only support mode even when the impersonated user normally has write
 * access; the backend remains the final authority for every request.
 */
export function canMutateSection(
  user: SectionUser | null | undefined,
  section: ProductSection,
  isImpersonating = false,
): boolean {
  return !isImpersonating && hasSectionAccess(user, section, "write");
}

export function rolesWithSectionAccess(
  section: ProductSection,
  required: Exclude<SectionAccess, "none"> = "read",
): UserRole[] {
  return ALL_USER_ROLES.filter(
    (role) =>
      ACCESS_RANK[ROLE_SECTION_ACCESS[role][section]] >= ACCESS_RANK[required],
  );
}
