import { actionAccessForRoles } from "@/lib/action-access";
import {
  PERMISSION_KEYS,
  closePermissions,
  defaultPermissionsForRoles,
  deriveSections,
  type Permission,
} from "@/lib/permissions";
import {
  PRODUCT_SECTIONS,
  sectionAccessForRoles,
  type ProductSection,
  type SectionAccess,
} from "@/lib/section-access";
import type { DataScope, User, UserRole } from "@/store/auth";

export interface AccessSnapshotOptions {
  /** Role dodatkowe konta (rola główna to pierwszy argument). */
  roles?: readonly UserRole[];
  /** Uprawnienia nadane ponad domyślne ról (osobie albo w przełączniku roli). */
  grant?: readonly Permission[];
  /** Uprawnienia wyłączone roli na ekranie Osoby i role. */
  revoke?: readonly Permission[];
  /**
   * Stary wyjątek osoby dla sekcji. Delivery i Finanse potrafi już tylko
   * OGRANICZYĆ (jak `effective_policy_from_rows` w backendzie).
   */
  sectionCaps?: Partial<Record<ProductSection, SectionAccess>>;
  /** Klienci z przypisania Delivery Leada (`data_scope.finance_client_ids`). */
  assignedClientIds?: readonly number[];
}

export type AccessSnapshot = Pick<User, "role" | "roles"> &
  Required<
    Pick<User, "effective_action_access" | "effective_section_access" | "capabilities">
  > &
  Pick<User, "data_scope">;

const RANK: Record<SectionAccess, number> = { none: 0, read: 1, write: 2 };
const lower = (a: SectionAccess, b: SectionAccess) => (RANK[a] <= RANK[b] ? a : b);

/**
 * Komplet dostępu konta w kształcie `GET /api/auth/me` po 0409: dziewięć
 * uprawnień (z zależnościami), wynikające z nich sekcje Delivery i Finanse,
 * capability finansowe i — dla konta z rolą Delivery Leada — portfel.
 *
 * Testy bramek budują użytkownika tędy, żeby oba komplety (`effective_action_access`
 * i `effective_section_access`) były ze sobą zgodne tak jak z serwera. Sam
 * `{ role }` też jest poprawnym użytkownikiem: to profil sprzed wdrożenia,
 * liczony z domyślnych uprawnień ról.
 */
export function accessSnapshot(
  role: UserRole,
  options: AccessSnapshotOptions = {},
): AccessSnapshot {
  const roles = [...new Set<UserRole>([role, ...(options.roles ?? [])])];
  const isAdmin = roles.includes("admin");
  const revoked = new Set<Permission>(options.revoke ?? []);
  const held = isAdmin
    ? new Set<Permission>(PERMISSION_KEYS)
    : closePermissions([
        ...[...defaultPermissionsForRoles(roles)].filter((key) => !revoked.has(key)),
        ...(options.grant ?? []),
      ]);

  const effective_action_access: NonNullable<User["effective_action_access"]> = {
    b2b_contract_generator: actionAccessForRoles(roles, "b2b_contract_generator"),
  };
  for (const key of PERMISSION_KEYS) {
    effective_action_access[key] = held.has(key) ? "manage" : "none";
  }

  const derived = deriveSections(held);
  const effective_section_access = {} as Record<ProductSection, SectionAccess>;
  for (const section of PRODUCT_SECTIONS) {
    const base: SectionAccess = isAdmin
      ? "write"
      : section === "delivery" || section === "finance"
        ? derived[section]
        : sectionAccessForRoles(roles, section);
    const cap = options.sectionCaps?.[section];
    effective_section_access[section] = cap === undefined ? base : lower(base, cap);
  }

  const finance = effective_section_access.finance;
  const capabilities =
    finance === "write"
      ? ["view_finance", "manage_finance"]
      : finance === "read"
        ? ["view_finance"]
        : [];

  const governedByPortfolio =
    roles.includes("delivery_lead") && !isAdmin && !roles.includes("finance");
  const data_scope: DataScope | undefined = governedByPortfolio
    ? {
        kind: "delivery_clients",
        user_id: 1,
        allowed_client_ids: [...(options.assignedClientIds ?? [])],
        allowed_tac_user_ids: [],
        allowed_operator_user_ids: [],
        finance_client_ids: [...(options.assignedClientIds ?? [])],
      }
    : undefined;

  return {
    role,
    roles,
    effective_action_access,
    effective_section_access,
    capabilities,
    data_scope,
  };
}
