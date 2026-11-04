/**
 * Ustawienia → Zespół i dostęp → „Osoby i role”: kształty odpowiedzi API
 * (kontrakt: `docs/permissions-nine-switches-contract.md` §7) i czysta logika
 * widoku — bez Reacta, żeby dało się ją sprawdzić na wartościach.
 *
 * Zależności między uprawnieniami liczy `lib/permissions.ts` (jeden katalog
 * z backendem). Tu jest tylko to, co z nich wynika dla ekranu: stan
 * przełączników, lista zmian do wysłania i zdania, które je opisują.
 */
import type {
  ActionAccess,
  ProductAction,
  UserActionOverrideAccess,
} from "@/lib/action-access";
import { refusalCode } from "@/lib/help/refusal-tracker";
import {
  PERMISSION_KEYS,
  closePermissions,
  impliedBy,
  isPermission,
  permissionLabel,
  type Permission,
  type PermissionGroupKey,
} from "@/lib/permissions";
import { pluralPl } from "@/lib/plural-pl";
import {
  ALL_USER_ROLES,
  type ProductSection,
  type RoleSectionPermissions,
  type SectionAccess,
  type SectionPermissionsResponse,
  type UserSectionPermissionChange,
} from "@/lib/section-access";
import type { UserRole } from "@/store/auth";

// ── Kształty API ─────────────────────────────────────────────────────────────

/** Klucz akcji w tabelach RBAC: poziom generatora B2B albo jedno z dziewięciu uprawnień. */
export type AdminActionKey = ProductAction | Permission;

export interface NamedPermissionState {
  /** Zapisany wiersz roli — to, co przełącza administrator. */
  granted: boolean;
  /** Po zależnościach: nadane albo wymuszone przez inne. */
  effective: boolean;
  /** Nadane uprawnienia, które wymuszają to uprawnienie. */
  implied_by: Permission[];
}

export interface AdminPermissionDefinition {
  key: Permission;
  label: string;
  group: PermissionGroupKey;
  requires: Permission[];
  default_roles: UserRole[];
}

export interface AdminPermissionGroup {
  key: PermissionGroupKey;
  label: string;
  permissions: Permission[];
}

export interface AdminRolePermissions
  extends Omit<RoleSectionPermissions, "action_permissions"> {
  action_permissions?: Partial<Record<AdminActionKey, ActionAccess>>;
  /** Aktywne konta z tą rolą (główną albo dodatkową). */
  users_count: number;
  /** `false` dla administratora (ma wszystko) oraz ról `user` i `trainee`. */
  grantable: boolean;
  named: Partial<Record<Permission, NamedPermissionState>>;
}

/** `GET /api/admin/section-permissions`. */
export interface AdminPermissionsSnapshot
  extends Omit<SectionPermissionsResponse, "roles" | "actions"> {
  roles: AdminRolePermissions[];
  actions?: AdminActionKey[];
  /** Sekcje, których poziom wynika z uprawnień (Delivery, Finanse). */
  derived_sections: ProductSection[];
  permission_groups: AdminPermissionGroup[];
  permissions: AdminPermissionDefinition[];
}

export interface AdminUserPermissions {
  user_id: number;
  name: string;
  role: UserRole;
  roles: UserRole[];
  /** Administrator: ma wszystko, niczego się mu nie nadaje. */
  locked: boolean;
  /** `false` dla kont z rolą `user` albo `trainee`. */
  grantable: boolean;
  /** To, co dają role konta (po zależnościach). */
  role_permissions: Permission[];
  /** Uprawnienia nadane tej osobie. */
  grants: Permission[];
  /** Uprawnienia odebrane tej osobie (pozycja „Odebrane” w oknie). */
  restrictions: Permission[];
  effective: Permission[];
  /** Stare wyjątki sekcji Delivery/Finanse — tylko ograniczają. */
  legacy_section_caps: Partial<Record<ProductSection, SectionAccess>>;
}

/** `GET /api/admin/section-permissions/users/{user_id}`. */
export interface AdminUserPermissionsResponse {
  revision: number;
  user: AdminUserPermissions;
}

export interface RolePermissionChange {
  role: UserRole;
  action: AdminActionKey;
  access: ActionAccess;
}

export interface UserPermissionChange {
  action: AdminActionKey;
  access: UserActionOverrideAccess;
}

/**
 * 409 „ktoś zapisał w międzyczasie” — jedyna odmowa, po której wczytujemy
 * zasady od nowa. Zapis potrafi odpowiedzieć 409 także wtedy, gdy baza nie
 * przyjęła wiersza (`permission_storage_rejected`): wtedy szkic zostaje,
 * a ekran pokazuje zdanie z serwera, więc sam status nie wystarcza.
 */
export function isStalePolicyError(error: unknown): boolean {
  const response = (
    error as { response?: { status?: unknown; data?: unknown } } | null
  )?.response;
  return (
    typeof response?.status === "number" &&
    refusalCode(response.status, response.data) === "stale_section_policy"
  );
}

// ── Zakładka „Uprawnienia”: jedna rola, dziewięć przełączników ────────────────

const ROLE_ORDER = new Map<string, number>(
  ALL_USER_ROLES.map((role, index) => [role, index]),
);

/**
 * Odpowiedź sprzed wdrożenia uprawnień nie niesie ani listy, ani ról do
 * nadania. Taki odczyt jest awarią, nie „rolą bez uprawnień” — ekran zbudowany
 * z niego pokazałby dziewięć wyłączonych przełączników i pozwolił je zapisać.
 */
export function snapshotIsUsable(
  snapshot: AdminPermissionsSnapshot | null | undefined,
): snapshot is AdminPermissionsSnapshot {
  return (
    !!snapshot &&
    Array.isArray(snapshot.permissions) &&
    snapshot.permissions.some((permission) => isPermission(permission.key)) &&
    Array.isArray(snapshot.permission_groups) &&
    snapshot.permission_groups.length > 0 &&
    Array.isArray(snapshot.roles) &&
    snapshot.roles.some((entry) => entry.grantable === true)
  );
}

/** Role, którym da się nadać uprawnienia — bez administratora, `user` i `trainee`. */
export function grantableRoles(
  snapshot: AdminPermissionsSnapshot,
): AdminRolePermissions[] {
  return snapshot.roles
    .filter((entry) => entry.grantable === true)
    .sort(
      (a, b) =>
        (ROLE_ORDER.get(a.role) ?? ROLE_ORDER.size) -
        (ROLE_ORDER.get(b.role) ?? ROLE_ORDER.size),
    );
}

/** Uprawnienia zapisane w wierszach roli (bez tych, które tylko z nich wynikają). */
export function grantedPermissions(role: AdminRolePermissions): Set<Permission> {
  return new Set(
    PERMISSION_KEYS.filter((key) => role.named?.[key]?.granted === true),
  );
}

export function togglePermission(
  draft: ReadonlySet<Permission>,
  key: Permission,
): Set<Permission> {
  const next = new Set(draft);
  if (!next.delete(key)) next.add(key);
  return next;
}

export interface PermissionRow {
  key: Permission;
  label: string;
  /** Stan przełącznika po lokalnych zmianach: nadane albo wymuszone. */
  on: boolean;
  /** Włączone uprawnienia, które wymuszają to — przełącznik jest zablokowany. */
  requiredBy: Permission[];
  /** Stan przełącznika zapisany dziś na serwerze. */
  onToday: boolean;
  /** Po zapisaniu przełącznik będzie w innym stanie niż dziś. */
  changed: boolean;
}

export interface PermissionRowGroup {
  key: PermissionGroupKey;
  label: string;
  rows: PermissionRow[];
}

/**
 * Wiersze ekranu w kolejności i z nazwami z API. „Zmiana” znaczy tu: po
 * zapisaniu rola będzie mogła co innego niż dziś — także wtedy, gdy
 * uprawnienie włączyło się jako wymagane przez inne.
 */
export function rolePermissionGroups(
  snapshot: AdminPermissionsSnapshot,
  role: AdminRolePermissions,
  draft: ReadonlySet<Permission>,
): PermissionRowGroup[] {
  const labels = new Map(
    snapshot.permissions.map((permission) => [permission.key, permission.label]),
  );
  return snapshot.permission_groups.map((group) => ({
    key: group.key,
    label: group.label,
    rows: group.permissions.filter(isPermission).map((key) => {
      const requiredBy = impliedBy(key, draft);
      const on = draft.has(key) || requiredBy.length > 0;
      const onToday = role.named?.[key]?.effective === true;
      return {
        key,
        label: labels.get(key) ?? permissionLabel(key),
        on,
        requiredBy,
        onToday,
        changed: on !== onToday,
      };
    }),
  }));
}

/**
 * Zmiany wierszy roli do wysłania. Wiersz, który po zmianach i tak wynika
 * z innego włączonego uprawnienia, nie jest wysyłany: jego stan na ekranie
 * się nie zmienia, a zapis dałby „zmianę”, której nie widać. Dzięki temu lista
 * jest pusta dokładnie wtedy, gdy żaden przełącznik nie różni się od stanu
 * z serwera (pilnuje tego test po wszystkich kombinacjach).
 */
export function rolePermissionChanges(
  role: AdminRolePermissions,
  draft: ReadonlySet<Permission>,
): RolePermissionChange[] {
  const granted = grantedPermissions(role);
  return PERMISSION_KEYS.filter(
    (key) =>
      draft.has(key) !== granted.has(key) && impliedBy(key, draft).length === 0,
  ).map((key) => ({
    role: role.role,
    action: key,
    access: draft.has(key) ? "manage" : "none",
  }));
}

export function changedRows(groups: readonly PermissionRowGroup[]): PermissionRow[] {
  return groups.flatMap((group) => group.rows.filter((row) => row.changed));
}

function quoted(label: string): string {
  return `„${label}”`;
}

/** Nazwy uprawnień w cudzysłowach, po przecinku. */
export function quotedPermissionLabels(keys: readonly Permission[]): string {
  return keys.map((key) => quoted(permissionLabel(key))).join(", ");
}

/** „Wymagane przez: „Stawki i kwoty: zmiana”” — podpis zablokowanego wiersza. */
export function requiredByCaption(requiredBy: readonly Permission[]): string {
  return `Wymagane przez: ${quotedPermissionLabels(requiredBy)}`;
}

export function peopleCountLabel(count: number): string {
  return `${count} ${pluralPl(count, "osoba", "osoby", "osób")}`;
}

export function changesCountLabel(count: number): string {
  if (count === 0) return "Brak niezapisanych zmian";
  return `${count} ${pluralPl(count, "zmiana", "zmiany", "zmian")} do zapisania`;
}

/** Zdanie o wylogowaniu w oknie potwierdzenia — zgodne z liczbą osób. */
export function logoutSentence(count: number, roleLabel: string): string {
  if (count === 0) {
    return `Nikt nie ma dziś roli ${roleLabel}, więc nikt nie zostanie wylogowany.`;
  }
  const people = `${count} ${pluralPl(count, "osoba", "osoby", "osób")} z rolą ${roleLabel}`;
  const outcome = pluralPl(
    count,
    "zostanie wylogowana i zaloguje się ponownie",
    "zostaną wylogowane i zalogują się ponownie",
    "zostanie wylogowanych i zaloguje się ponownie",
  );
  return `Po zapisaniu ${people} ${outcome}.`;
}

/** Plakietka przy osobie: „+1 uprawnienie”, „+2 uprawnienia”, „+5 uprawnień”. */
export function extraPermissionsLabel(count: number): string {
  return `+${count} ${pluralPl(count, "uprawnienie", "uprawnienia", "uprawnień")}`;
}

/** Nazwy uprawnień do podpowiedzi plakietki; nieznany klucz zostaje kluczem. */
export function extraPermissionsTitle(keys: readonly string[]): string {
  return keys
    .map((key) => (isPermission(key) ? permissionLabel(key) : key))
    .join(", ");
}

// ── „Edytuj użytkownika”: uprawnienia jednej osoby ───────────────────────────

/**
 * Konto przyjmuje wyjątki, gdy KAŻDA z jego ról jest do nadania: administrator
 * ma wszystko, a `user` i `trainee` nie dostają niczego.
 */
export function rolesAcceptGrants(
  snapshot: AdminPermissionsSnapshot,
  roles: readonly string[],
): boolean {
  if (roles.length === 0) return false;
  const byRole = new Map<string, AdminRolePermissions>(
    snapshot.roles.map((entry) => [entry.role, entry]),
  );
  return roles.every((role) => byRole.get(role)?.grantable === true);
}

/** Wiersze zapisane w wybranych rolach, bez tego, co tylko z nich wynika. */
export function grantedByRoles(
  snapshot: AdminPermissionsSnapshot,
  roles: readonly string[],
): Set<Permission> {
  const selected = new Set(roles);
  return new Set(
    snapshot.roles
      .filter((entry) => selected.has(entry.role))
      .flatMap((entry) => [...grantedPermissions(entry)]),
  );
}

/** To, co dają wskazane role razem (po zależnościach). */
export function permissionsOfRoles(
  snapshot: AdminPermissionsSnapshot,
  roles: readonly string[],
): Set<Permission> {
  return closePermissions(grantedByRoles(snapshot, roles));
}

/** Wyjątek osoby: uprawnienie nadane ponad rolę albo odebrane mimo roli. */
export type PersonOverride = "manage" | "none";
export type PersonOverrides = ReadonlyMap<Permission, PersonOverride>;

export function storedPersonOverrides(user: AdminUserPermissions): Map<Permission, PersonOverride> {
  return new Map<Permission, PersonOverride>([
    ...(user.grants ?? []).filter(isPermission).map((key) => [key, "manage"] as const),
    ...(user.restrictions ?? []).filter(isPermission).map((key) => [key, "none"] as const),
  ]);
}

/** Lustro resolvera: wiersze ról zastąpione wyjątkami osoby, przed zależnościami. */
function heldBeforeClosure(
  roleGranted: ReadonlySet<Permission>,
  overrides: PersonOverrides,
): Set<Permission> {
  const held = new Set(roleGranted);
  overrides.forEach((access, key) => {
    if (access === "manage") held.add(key);
    else held.delete(key);
  });
  return held;
}

export interface PersonPermissionRow {
  key: Permission;
  label: string;
  /** Wybrane role dają to uprawnienie: „Z roli” / „Odebrane”, inaczej „Brak” / „Nadane”. */
  fromRole: boolean;
  /** Osoba będzie je mieć po zapisaniu. */
  on: boolean;
  /** Zachowane uprawnienia, które go wymagają — przełącznik jest zablokowany. */
  requiredBy: Permission[];
}

/** Wszystkie uprawnienia z katalogu w kolejności grup, ze stanem po zmianach w oknie. */
export function personPermissionRows(
  snapshot: AdminPermissionsSnapshot,
  roleGranted: ReadonlySet<Permission>,
  overrides: PersonOverrides,
  /** Grupy, których nie pokazujemy (np. „people” przy wyłączonym programie). */
  hiddenGroups: ReadonlySet<string> = new Set(),
): PersonPermissionRow[] {
  const labels = new Map(
    snapshot.permissions.map((permission) => [permission.key, permission.label]),
  );
  const fromRoles = closePermissions(roleGranted);
  const held = heldBeforeClosure(roleGranted, overrides);
  const effective = closePermissions(held);
  return snapshot.permission_groups
    .filter((group) => !hiddenGroups.has(group.key))
    .flatMap((group) => group.permissions)
    .filter(isPermission)
    .map((key) => ({
      key,
      label: labels.get(key) ?? permissionLabel(key),
      fromRole: fromRoles.has(key),
      on: effective.has(key),
      requiredBy: impliedBy(key, held),
    }));
}

/** Przełącza wiersz: wyjątek powstaje tylko wtedy, gdy wybór różni się od wierszy ról. */
export function setPersonPermission(
  overrides: PersonOverrides,
  roleGranted: ReadonlySet<Permission>,
  key: Permission,
  on: boolean,
): Map<Permission, PersonOverride> {
  const next = new Map(overrides);
  if (on === roleGranted.has(key)) next.delete(key);
  else next.set(key, on ? "manage" : "none");
  return next;
}

/**
 * Wyjątki, które coś zmieniają: nadanie tego, co dają role, i odebranie tego,
 * czego nie dają, są puste. Odebrane, którego wymaga uprawnienie zachowane
 * w tym samym oknie, też odpada — ekran pokazuje je jako włączone, a serwer
 * takiego zapisu nie przyjmie (`permission_required_by_kept`).
 */
function meaningfulOverrides(
  overrides: PersonOverrides,
  roleGranted: ReadonlySet<Permission>,
): Map<Permission, PersonOverride> {
  const kept = new Map(
    [...overrides].filter(([key, access]) => (access === "manage") !== roleGranted.has(key)),
  );
  const held = heldBeforeClosure(roleGranted, kept);
  kept.forEach((access, key) => {
    if (access === "none" && impliedBy(key, held).length > 0) kept.delete(key);
  });
  return kept;
}

function sameOverrides(left: PersonOverrides, right: PersonOverrides): boolean {
  return (
    left.size === right.size &&
    [...left].every(([key, access]) => right.get(key) === access)
  );
}

const SECTION_NAMES: Partial<Record<ProductSection, string>> = {
  delivery: "Delivery",
  finance: "Finanse",
};

const CAP_NAMES: Record<SectionAccess, string> = {
  none: "brak dostępu",
  read: "tylko odczyt",
  write: "odczyt i zapis",
};

/** Stare limity sekcji Delivery/Finanse, nazwane słowami; pusta lista = nie ma czego usuwać. */
export function legacyLimits(user: AdminUserPermissions): string[] {
  return Object.entries(user.legacy_section_caps ?? {}).map(
    ([section, access]) =>
      `${SECTION_NAMES[section as ProductSection] ?? section}: ${CAP_NAMES[access as SectionAccess] ?? access}`,
  );
}

export interface UserPermissionsSave {
  revision: number;
  changes: UserSectionPermissionChange[];
  actionChanges: UserPermissionChange[];
}

/**
 * Drugie żądanie zapisu z okna „Edytuj użytkownika” — albo `null`, gdy nie ma
 * czego wysyłać.
 *
 * Wyjątek, który po wyborach w oknie niczego nie zmienia, wraca do `inherit`.
 * Samo takie sprzątanie nie wystarcza jednak do zapisu: zmiana uprawnień
 * wylogowuje osobę, więc poprawka nazwiska nie może przy okazji zakończyć jej
 * sesji. Wysyłamy tylko wtedy, gdy administrator coś przełączył, zmienił role
 * albo kazał usunąć stare limity sekcji.
 */
export function userPermissionsSave({
  response,
  draft,
  roleGranted,
  rolesChanged,
  removeLegacy,
}: {
  response: AdminUserPermissionsResponse;
  draft: PersonOverrides;
  roleGranted: ReadonlySet<Permission>;
  rolesChanged: boolean;
  removeLegacy: boolean;
}): UserPermissionsSave | null {
  const stored = storedPersonOverrides(response.user);
  const wanted = meaningfulOverrides(draft, roleGranted);
  if (
    !rolesChanged &&
    !removeLegacy &&
    sameOverrides(meaningfulOverrides(stored, roleGranted), wanted)
  ) {
    return null;
  }

  const actionChanges: UserPermissionChange[] = PERMISSION_KEYS.filter(
    (key) => stored.get(key) !== wanted.get(key),
  ).map((key) => ({ action: key, access: wanted.get(key) ?? "inherit" }));

  const changes: UserSectionPermissionChange[] = removeLegacy
    ? Object.keys(response.user.legacy_section_caps ?? {}).map((section) => ({
        section: section as ProductSection,
        access: "inherit",
      }))
    : [];

  if (actionChanges.length === 0 && changes.length === 0) return null;
  return { revision: response.revision, changes, actionChanges };
}
