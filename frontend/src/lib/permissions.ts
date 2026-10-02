/**
 * Dziewięć uprawnień z ekranu Ustawienia → Zespół i dostęp → Osoby i role.
 *
 * Katalog (nazwy, grupy, zależności, domyślni posiadacze) to plik
 * `permission-catalog.json` — ten sam, który asertuje backend
 * (`backend/tests/test_permission_catalog.py`), więc oba stosy czytają jedno.
 *
 * Backend jest źródłem prawdy: `GET /api/auth/me` zwraca w
 * `effective_action_access` komplet uprawnień konta (po zależnościach
 * i wyjątkach osoby). Frontend używa ich wyłącznie do tego, co POKAZAĆ.
 */
import type { UserRole } from "@/store/auth";

import catalog from "./permission-catalog.json";

export type Permission =
  | "delivery_view"
  | "clients_edit"
  | "contracts_orders_edit"
  | "contract_status"
  | "b2b_signature_confirmation"
  | "recruitment_manage"
  | "amounts_view"
  | "amounts_edit"
  | "finance_module";

export type PermissionGroupKey = "clients_contracts" | "recruitment" | "money";

export interface PermissionDefinition {
  key: Permission;
  label: string;
  group: PermissionGroupKey;
  /** Uprawnienia, które to uprawnienie pociąga za sobą. */
  requires: readonly Permission[];
  /** Role, które mają je domyślnie (poza administratorem). */
  default_roles: readonly UserRole[];
}

export interface PermissionGroup {
  key: PermissionGroupKey;
  label: string;
  permissions: readonly Permission[];
}

export const PERMISSIONS = catalog.permissions as readonly PermissionDefinition[];
export const PERMISSION_GROUPS = catalog.groups as readonly PermissionGroup[];
export const PERMISSION_KEYS: readonly Permission[] = PERMISSIONS.map(
  (permission) => permission.key,
);

const BY_KEY = new Map(PERMISSIONS.map((permission) => [permission.key, permission]));

export function isPermission(value: string): value is Permission {
  return BY_KEY.has(value as Permission);
}

export function permissionLabel(key: Permission): string {
  return BY_KEY.get(key)?.label ?? key;
}

/** Nadane uprawnienia razem z tymi, które z nich wynikają. */
export function closePermissions(granted: Iterable<Permission>): Set<Permission> {
  const effective = new Set<Permission>();
  const pending = [...granted].filter(isPermission);
  while (pending.length > 0) {
    const key = pending.pop() as Permission;
    if (effective.has(key)) continue;
    effective.add(key);
    pending.push(...(BY_KEY.get(key)?.requires ?? []));
  }
  return effective;
}

/** Które z nadanych uprawnień wymuszają `key` (opis zablokowanego przełącznika). */
export function impliedBy(
  key: Permission,
  granted: Iterable<Permission>,
): Permission[] {
  const held = new Set(granted);
  return PERMISSION_KEYS.filter(
    (other) =>
      other !== key && held.has(other) && closePermissions([other]).has(key),
  );
}

/** Domyślny zestaw ról z ekranu, z zależnościami. Administrator ma wszystko. */
export function defaultPermissionsForRoles(
  roles: Iterable<UserRole>,
): Set<Permission> {
  const held = new Set(roles);
  if (held.has("admin")) return new Set(PERMISSION_KEYS);
  return closePermissions(
    PERMISSIONS.filter((permission) =>
      permission.default_roles.some((role) => held.has(role)),
    ).map((permission) => permission.key),
  );
}

/** Poziom sekcji Delivery i Finanse wynikający z uprawnień (lustro backendu). */
export function deriveSections(effective: Iterable<Permission>): {
  delivery: "none" | "read" | "write";
  finance: "none" | "write";
} {
  const held = new Set(effective);
  const writesDelivery =
    held.has("clients_edit") ||
    held.has("contracts_orders_edit") ||
    held.has("contract_status") ||
    held.has("amounts_edit");
  return {
    delivery: writesDelivery ? "write" : held.has("delivery_view") ? "read" : "none",
    finance: held.has("finance_module") ? "write" : "none",
  };
}

export interface PermissionUser {
  role: UserRole;
  roles?: readonly UserRole[];
  effective_action_access?: Partial<Record<string, string>> | null;
}

/**
 * Profil zapisany w przeglądarce przed wdrożeniem uprawnień nie niesie nowych
 * kluczy. Taki profil liczymy z domyślnych uprawnień ról — do chwili, gdy
 * `AppShellV2` dociągnie świeże `/api/auth/me` (inaczej pierwsza odsłona po
 * wdrożeniu chowałaby Delivery każdemu).
 */
function hasAuthoritativeSnapshot(
  snapshot: PermissionUser["effective_action_access"],
): snapshot is Partial<Record<string, string>> {
  return Boolean(snapshot) && "delivery_view" in (snapshot as object);
}

export function permissionsOfUser(
  user: PermissionUser | null | undefined,
): Set<Permission> {
  if (!user) return new Set();
  const snapshot = user.effective_action_access;
  if (hasAuthoritativeSnapshot(snapshot)) {
    return new Set(PERMISSION_KEYS.filter((key) => snapshot[key] === "manage"));
  }
  return defaultPermissionsForRoles(
    new Set<UserRole>([user.role, ...(user.roles ?? [])]),
  );
}

export function hasPermission(
  user: PermissionUser | null | undefined,
  permission: Permission,
): boolean {
  return permissionsOfUser(user).has(permission);
}

export function hasAnyPermission(
  user: PermissionUser | null | undefined,
  ...permissions: Permission[]
): boolean {
  const held = permissionsOfUser(user);
  return permissions.some((permission) => held.has(permission));
}

/**
 * Czy zakres klientów konta wyznacza portfel Delivery Leada (lustro
 * `access_scope.is_delivery_lead_governed`). Uprawnienie mówi, CO konto może;
 * ta funkcja — U KOGO: konto z rolą DL działa u swoich klientów, każdy inny
 * posiadacz uprawnienia u wszystkich.
 */
export function isDeliveryLeadGoverned(
  user: Pick<PermissionUser, "role" | "roles"> | null | undefined,
): boolean {
  if (!user) return false;
  const roles = new Set<UserRole>([user.role, ...(user.roles ?? [])]);
  return roles.has("delivery_lead") && !roles.has("admin") && !roles.has("finance");
}
