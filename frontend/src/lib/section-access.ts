import type { UserRole } from "@/store/auth";

export type ProductSection =
  | "sourcing"
  | "pipeline"
  | "delivery"
  | "insights"
  | "finance"
  | "system_admin";

export type SectionAccess = "none" | "read" | "write";

export interface SectionUser {
  role: UserRole;
  roles?: readonly UserRole[];
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

export function rolesWithSectionAccess(
  section: ProductSection,
  required: Exclude<SectionAccess, "none"> = "read",
): UserRole[] {
  return ALL_USER_ROLES.filter(
    (role) =>
      ACCESS_RANK[ROLE_SECTION_ACCESS[role][section]] >= ACCESS_RANK[required],
  );
}
