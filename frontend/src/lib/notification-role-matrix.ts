/**
 * Ustawienia → Powiadomienia → „Kto co dostaje”: kształt odpowiedzi
 * `GET /api/settings/notification-roles` i czysta logika tabeli — bez Reacta
 * i bez sieci, żeby dało się ją sprawdzić na wartościach.
 *
 * Kategorie, grupy, role i to, które kategorie są obowiązkowe, zna wyłącznie
 * backend (`services/notification_role_view.py`). Tu jest tylko to, co z nich
 * wynika dla ekranu: szkic zmian, stan przełączników, średnia na osobę i lista
 * komórek do wysłania.
 */
import { pluralPl } from "@/lib/plural-pl";

// ── Kształty API ─────────────────────────────────────────────────────────────

export interface NotificationRoleColumn {
  key: string;
  label: string;
  /** Aktywne konta z tą rolą (główną albo dodatkową). */
  accounts: number;
}

export interface NotificationRoleGroup {
  key: string;
  label: string;
  muted: Record<string, boolean>;
  muted_at: Record<string, string | null>;
  /** Powiadomienia tej grupy do kont z rolą (główną) w ostatnich 30 dniach. */
  received_30d: Record<string, number>;
}

export interface NotificationRoleCategory {
  key: string;
  label: string;
  description: string;
  /** Kategorii obowiązkowej nie da się wyłączyć żadnej roli. */
  mandatory: boolean;
  /** Jedna grupa (ten sam klucz co kategoria) albo kilka. */
  groups: NotificationRoleGroup[];
}

export interface NotificationRolesView {
  revision: number;
  updated_at: string | null;
  updated_by_name: string | null;
  window_days: number;
  roles: NotificationRoleColumn[];
  categories: NotificationRoleCategory[];
}

export interface NotificationRoleChange {
  role: string;
  group: string;
  muted: boolean;
}

// ── Szkic ────────────────────────────────────────────────────────────────────

/**
 * Szkic trzyma WYŁĄCZNIE komórki, które różnią się od stanu z serwera
 * (klucz komórki → docelowe „wyłączone”). Dzięki temu „Zmiany: 0” znaczy
 * dokładnie: żaden przełącznik nie różni się od zapisanego.
 */
export type RoleMatrixDraft = Readonly<Record<string, boolean>>;

export const EMPTY_ROLE_MATRIX_DRAFT: RoleMatrixDraft = Object.freeze({});

export function cellKey(role: string, group: string): string {
  return `${role}|${group}`;
}

function savedMuted(group: NotificationRoleGroup, role: string): boolean {
  return group.muted[role] === true;
}

/** Czy grupa jest wyłączona dla roli — po zmianach ze szkicu. */
export function isGroupMuted(
  group: NotificationRoleGroup,
  role: string,
  draft: RoleMatrixDraft,
): boolean {
  const override = draft[cellKey(role, group.key)];
  return override === undefined ? savedMuted(group, role) : override;
}

export function isCellChanged(
  group: NotificationRoleGroup,
  role: string,
  draft: RoleMatrixDraft,
): boolean {
  return isGroupMuted(group, role, draft) !== savedMuted(group, role);
}

function withCells(
  draft: RoleMatrixDraft,
  role: string,
  groups: readonly NotificationRoleGroup[],
  muted: boolean,
): RoleMatrixDraft {
  const next: Record<string, boolean> = { ...draft };
  for (const group of groups) {
    const key = cellKey(role, group.key);
    if (savedMuted(group, role) === muted) delete next[key];
    else next[key] = muted;
  }
  return next;
}

function findCategory(
  view: NotificationRolesView,
  categoryKey: string,
): NotificationRoleCategory | undefined {
  return view.categories.find((category) => category.key === categoryKey);
}

/** Przełącz jedną grupę dla roli. Kategoria obowiązkowa zostaje nietknięta. */
export function toggleGroup(
  view: NotificationRolesView,
  draft: RoleMatrixDraft,
  role: string,
  groupKey: string,
): RoleMatrixDraft {
  for (const category of view.categories) {
    const group = category.groups.find((entry) => entry.key === groupKey);
    if (!group) continue;
    if (category.mandatory) return draft;
    return withCells(draft, role, [group], !isGroupMuted(group, role, draft));
  }
  return draft;
}

export type CategorySwitchState = "on" | "off" | "mixed";

/** Stan przełącznika kategorii: włączony tylko, gdy włączone są wszystkie grupy. */
export function categoryState(
  category: NotificationRoleCategory,
  role: string,
  draft: RoleMatrixDraft,
): CategorySwitchState {
  const muted = category.groups.filter((group) =>
    isGroupMuted(group, role, draft),
  ).length;
  if (muted === 0) return "on";
  return muted === category.groups.length ? "off" : "mixed";
}

/**
 * Przełącznik kategorii = wszystkie jej grupy naraz: z „wszystko włączone”
 * wyłącza wszystkie, z każdego innego stanu włącza wszystkie.
 */
export function toggleCategory(
  view: NotificationRolesView,
  draft: RoleMatrixDraft,
  role: string,
  categoryKey: string,
): RoleMatrixDraft {
  const category = findCategory(view, categoryKey);
  if (!category || category.mandatory) return draft;
  const muteAll = categoryState(category, role, draft) === "on";
  return withCells(draft, role, category.groups, muteAll);
}

/** Komórki do wysłania w `PUT` — w kolejności tabeli, tylko realne zmiany. */
export function changedCells(
  view: NotificationRolesView,
  draft: RoleMatrixDraft,
): NotificationRoleChange[] {
  const changes: NotificationRoleChange[] = [];
  for (const category of view.categories) {
    if (category.mandatory) continue;
    for (const group of category.groups) {
      for (const role of view.roles) {
        if (isCellChanged(group, role.key, draft)) {
          changes.push({
            role: role.key,
            group: group.key,
            muted: isGroupMuted(group, role.key, draft),
          });
        }
      }
    }
  }
  return changes;
}

// ── Liczby ───────────────────────────────────────────────────────────────────

export function groupReceived(group: NotificationRoleGroup, role: string): number {
  return group.received_30d[role] ?? 0;
}

export function categoryReceived(
  category: NotificationRoleCategory,
  role: string,
): number {
  return category.groups.reduce(
    (sum, group) => sum + groupReceived(group, role),
    0,
  );
}

/**
 * „N na osobę”: powiadomienia WŁĄCZONYCH komórek roli z 30 dni podzielone
 * przez liczbę kont. `null`, gdy rola nie ma kont — nie ma kogo uśredniać,
 * a zero znaczyłoby „nikt nic nie dostaje”.
 */
export function perPersonAverage(
  view: NotificationRolesView,
  role: NotificationRoleColumn,
  draft: RoleMatrixDraft = EMPTY_ROLE_MATRIX_DRAFT,
): number | null {
  if (role.accounts <= 0) return null;
  let enabled = 0;
  for (const category of view.categories) {
    for (const group of category.groups) {
      if (!isGroupMuted(group, role.key, draft)) {
        enabled += groupReceived(group, role.key);
      }
    }
  }
  return Math.round(enabled / role.accounts);
}

/** Liczba z odstępem co trzy cyfry (twarda spacja — nie łamie się w komórce). */
export function formatCount(value: number): string {
  return String(Math.trunc(value)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
}

export function accountsLabel(accounts: number): string {
  return `${accounts} ${pluralPl(accounts, "konto", "konta", "kont")}`;
}

// ── Podsumowanie do okna potwierdzenia ───────────────────────────────────────

export interface RoleChangeSummary {
  role: NotificationRoleColumn;
  /** Grupy, które rola przestanie dostawać. */
  off: string[];
  /** Grupy, które rola zacznie znowu dostawać. */
  on: string[];
}

function summaryLabel(
  category: NotificationRoleCategory,
  group: NotificationRoleGroup,
): string {
  return category.groups.length > 1
    ? `${category.label}: ${group.label}`
    : category.label;
}

/** Zmiany pogrupowane po roli, w kolejności kolumn tabeli. */
export function changeSummary(
  view: NotificationRolesView,
  draft: RoleMatrixDraft,
): RoleChangeSummary[] {
  return view.roles
    .map((role) => {
      const summary: RoleChangeSummary = { role, off: [], on: [] };
      for (const category of view.categories) {
        if (category.mandatory) continue;
        for (const group of category.groups) {
          if (!isCellChanged(group, role.key, draft)) continue;
          const label = summaryLabel(category, group);
          if (isGroupMuted(group, role.key, draft)) summary.off.push(label);
          else summary.on.push(label);
        }
      }
      return summary;
    })
    .filter((summary) => summary.off.length > 0 || summary.on.length > 0);
}

/**
 * Kategorie z kilkoma grupami, które po wczytaniu mają stan mieszany dla
 * którejś roli — startują rozwinięte, bo zwinięty wiersz nie pokazałby,
 * która grupa jest wyłączona.
 */
export function initiallyExpanded(view: NotificationRolesView): string[] {
  return view.categories
    .filter(
      (category) =>
        category.groups.length > 1 &&
        view.roles.some(
          (role) =>
            categoryState(category, role.key, EMPTY_ROLE_MATRIX_DRAFT) === "mixed",
        ),
    )
    .map((category) => category.key);
}

/**
 * Odpowiedź bez ról albo bez kategorii to awaria odczytu, nie „pusta tabela”
 * — ekran zbudowany z niej wyglądałby jak brak powiadomień w firmie.
 */
export function viewIsUsable(
  view: NotificationRolesView | null | undefined,
): view is NotificationRolesView {
  return (
    !!view &&
    typeof view.revision === "number" &&
    Array.isArray(view.roles) &&
    view.roles.length > 0 &&
    Array.isArray(view.categories) &&
    view.categories.length > 0 &&
    view.categories.every((category) => Array.isArray(category.groups))
  );
}
