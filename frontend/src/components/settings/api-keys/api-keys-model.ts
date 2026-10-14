// Logika ekranu „Ustawienia → Klucze API” bez Reacta: grupy uprawnień, stan
// klucza, ostrzeżenie o wygaśnięciu, walidacja slugu i ważności. Funkcje
// zależne od czasu biorą `now` z parametru, żeby testy i harness nie zależały
// od zegara.

import type {
  ScopeInfoDto,
  ServiceAccountKeyDto,
} from "@/lib/api";
import { formatIsoDatePl } from "@/lib/date-pl";

// ── Uprawnienia ──────────────────────────────────────────────────────────────

export interface ScopeGroupDefinition {
  id: string;
  title: string;
  scopes: readonly string[];
}

/** Kolejność grup i scope'ów w grupie = kolejność na ekranie. Scope spoza
 *  tej listy (nowy w backendzie) trafia do „Inne”, nie znika. */
export const SCOPE_GROUPS: readonly ScopeGroupDefinition[] = [
  {
    id: "billing-read",
    title: "Rozliczenia — odczyt",
    scopes: [
      "clients:read",
      "contracts:read",
      "orders:read",
      "md:read",
      "finance:read",
      "invoices:read",
    ],
  },
  {
    id: "billing-write",
    title: "Rozliczenia — zapis",
    scopes: [
      "orders:write",
      "contracts:write",
      "contracts:status",
      "md:write",
      "finance:write",
      "invoices:write",
    ],
  },
  // Węższy przed szerszym: kwoty sprzedaży, potem wszystkie (z kosztami i marżą).
  {
    id: "amounts",
    title: "Kwoty",
    scopes: ["sales_amounts:read", "amounts:read", "amounts:write"],
  },
  {
    id: "ops",
    title: "Operacyjne",
    scopes: ["traffit:sync", "traffit:read", "ops:snapshot", "contractors:read"],
  },
];

export const OTHER_SCOPE_GROUP = { id: "other", title: "Inne" } as const;

export interface ScopeView {
  value: string;
  label: string;
}

export interface ScopeGroupView {
  id: string;
  title: string;
  scopes: ScopeView[];
}

/**
 * Podziel scope'y na grupy ekranu. Puste grupy znikają; etykieta pochodzi
 * z `/scopes`, a gdy jej brak — zostaje surowa wartość (np. scope, którego
 * backend już nie zna, a konto nadal go ma).
 */
export function groupScopes(
  values: readonly string[],
  catalog: readonly ScopeInfoDto[],
): ScopeGroupView[] {
  const present = new Set(values);
  const labelOf = (value: string) =>
    catalog.find((s) => s.value === value)?.label ?? value;
  const grouped = new Set(SCOPE_GROUPS.flatMap((g) => g.scopes));

  const groups: ScopeGroupView[] = SCOPE_GROUPS.map((group) => ({
    id: group.id,
    title: group.title,
    scopes: group.scopes
      .filter((value) => present.has(value))
      .map((value) => ({ value, label: labelOf(value) })),
  }));

  // „Inne”: najpierw w kolejności słownika z serwera, potem reszta.
  const catalogOrder = catalog.map((s) => s.value);
  const others = [...present]
    .filter((value) => !grouped.has(value))
    .sort((a, b) => {
      const ia = catalogOrder.indexOf(a);
      const ib = catalogOrder.indexOf(b);
      if (ia === -1 && ib === -1) return a.localeCompare(b);
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    });
  groups.push({
    id: OTHER_SCOPE_GROUP.id,
    title: OTHER_SCOPE_GROUP.title,
    scopes: others.map((value) => ({ value, label: labelOf(value) })),
  });

  return groups.filter((group) => group.scopes.length > 0);
}

/** Etykieta na chipie: bez dopisku w nawiasie („Zużycie MD: zapis (import, …)”
 *  → „Zużycie MD: zapis”); pełna etykieta idzie do podpowiedzi. */
export function shortScopeLabel(label: string): string {
  const short = label.replace(/\s*\([^)]*\)\s*$/, "").trim();
  return short || label;
}

/** Grupy do formularza: wszystko, co serwer pozwala nadać. */
export function groupScopeCatalog(catalog: readonly ScopeInfoDto[]): ScopeGroupView[] {
  return groupScopes(
    catalog.map((s) => s.value),
    catalog,
  );
}

// ── Klucze ───────────────────────────────────────────────────────────────────

export type KeyStatus = "active" | "expired" | "revoked";

export const KEY_STATUS_LABEL: Record<KeyStatus, string> = {
  active: "Aktywny",
  expired: "Wygasł",
  revoked: "Odwołany",
};

const DAY_MS = 24 * 60 * 60 * 1000;

/** Ostrzeżenie o wygaśnięciu pojawia się na tyle dni przed terminem. */
export const EXPIRY_WARNING_DAYS = 14;

type KeyTimes = Pick<ServiceAccountKeyDto, "expires_at" | "revoked_at">;

/** Odwołanie wygrywa z wygaśnięciem — to ono jest decyzją człowieka. */
export function keyStatus(key: KeyTimes, now: Date): KeyStatus {
  if (key.revoked_at) return "revoked";
  if (new Date(key.expires_at).getTime() <= now.getTime()) return "expired";
  return "active";
}

export type ExpiryWarning = { kind: "expired" } | { kind: "soon"; days: number };

/** Ostrzeżenie przy dacie wygaśnięcia; odwołany klucz go nie ma. */
export function expiryWarning(key: KeyTimes, now: Date): ExpiryWarning | null {
  if (key.revoked_at) return null;
  const left = new Date(key.expires_at).getTime() - now.getTime();
  if (left <= 0) return { kind: "expired" };
  const days = Math.ceil(left / DAY_MS);
  return days <= EXPIRY_WARNING_DAYS ? { kind: "soon", days } : null;
}

export function expiryWarningLabel(warning: ExpiryWarning): string {
  if (warning.kind === "expired") return "Wygasł";
  return warning.days === 1 ? "Wygasa w ciągu doby" : `Wygasa za ${warning.days} dni`;
}

const STATUS_ORDER: Record<KeyStatus, number> = { active: 0, expired: 1, revoked: 2 };

/** Aktywne na górze, potem wygasłe i odwołane; w grupie najnowsze pierwsze. */
export function sortKeys<T extends KeyTimes & Pick<ServiceAccountKeyDto, "created_at">>(
  keys: readonly T[],
  now: Date,
): T[] {
  return [...keys].sort((a, b) => {
    const byStatus = STATUS_ORDER[keyStatus(a, now)] - STATUS_ORDER[keyStatus(b, now)];
    if (byStatus !== 0) return byStatus;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });
}

export function countActiveKeys(keys: readonly KeyTimes[], now: Date): number {
  return keys.filter((key) => keyStatus(key, now) === "active").length;
}

/** „1 aktywny klucz”, „3 aktywne klucze”, „5 aktywnych kluczy”. */
export function activeKeysLabel(count: number): string {
  if (count === 0) return "Brak aktywnego klucza";
  if (count === 1) return "1 aktywny klucz";
  const tens = count % 100;
  const units = count % 10;
  if (units >= 2 && units <= 4 && (tens < 12 || tens > 14)) return `${count} aktywne klucze`;
  return `${count} aktywnych kluczy`;
}

/** „5 min temu”, „3 h temu”, „12 dni temu”, starsze — data. */
export function formatAgo(iso: string, now: Date): string {
  const diff = now.getTime() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "przed chwilą";
  if (minutes < 60) return `${minutes} min temu`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h temu`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "wczoraj";
  if (days < 30) return `${days} dni temu`;
  return formatIsoDatePl(iso);
}

export function lastUsedLabel(
  key: Pick<ServiceAccountKeyDto, "last_used_at" | "last_used_ip">,
  now: Date,
): string {
  if (!key.last_used_at) return "Nigdy";
  const ago = formatAgo(key.last_used_at, now);
  return key.last_used_ip ? `${ago} · ${key.last_used_ip}` : ago;
}

// ── Formularze ───────────────────────────────────────────────────────────────

/** Lustro `_SLUG_RE` z `backend/app/schemas/service_account.py`. */
export const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

export function normalizeSlug(raw: string): string {
  return raw.trim().toLowerCase();
}

export function slugError(raw: string): string | null {
  const slug = normalizeSlug(raw);
  if (!slug) return "Podaj identyfikator konta.";
  if (!SLUG_PATTERN.test(slug)) {
    return "Identyfikator: 3–64 znaki, małe litery, cyfry i myślniki; bez myślnika na początku i na końcu.";
  }
  return null;
}

export type TtlResult = { days: number; error: null } | { days: null; error: string };

/** Ważność klucza w dniach: liczba całkowita 1…`maxDays` (sufit z `/config`). */
export function parseTtlDays(raw: string, maxDays: number): TtlResult {
  const trimmed = raw.trim();
  if (!trimmed) return { days: null, error: "Podaj ważność klucza w dniach." };
  if (!/^\d+$/.test(trimmed)) {
    return { days: null, error: "Ważność to liczba dni (liczba całkowita)." };
  }
  const days = Number(trimmed);
  if (days < 1) return { days: null, error: "Ważność to co najmniej 1 dzień." };
  if (days > maxDays) return { days: null, error: `Najdłuższa ważność to ${maxDays} dni.` };
  return { days, error: null };
}

/** Data wygaśnięcia klucza wydanego teraz na `days` dni (podpowiedź w formularzu). */
export function expiryPreview(days: number, now: Date): string {
  return formatIsoDatePl(new Date(now.getTime() + days * DAY_MS).toISOString());
}

// ── Zapisy przez API ─────────────────────────────────────────────────────────

const WRITE_STATE_LABEL: Record<string, string> = {
  pending: "W toku",
  done: "Zapisano",
};

export function writeStateLabel(state: string): string {
  return WRITE_STATE_LABEL[state] ?? state;
}
