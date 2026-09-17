/**
 * Konflikty kandydat↔klient — wspólne klocki frontu (widżet kandydata, sekcja
 * profilu klienta, rejestr w Ustawieniach).
 *
 * Od 17.09.2026 (decyzja Artura) konflikt z klientem jest OSTRZEŻENIEM, nie
 * blokadą: kandydat pozostaje widoczny i przypisywalny, a wpis w rejestrze
 * służy temu, żeby rekruter wiedział, z czym ma do czynienia.
 *
 * Wygaśnięcie NIE przełącza `active` — wiersz zostaje historią, a stan
 * `expired` liczy backend przy odczycie (`ConflictRow.state`).
 */

import type {
  ConflictRegistryParams,
  ConflictRegistryStateFilter,
  ConflictRow,
  ConflictState,
  ConflictType,
  MatchEligibility,
} from "@/lib/api";

/** Klucze react-query. Mutacje unieważniają `conflictKeys.all`. */
export const conflictKeys = {
  all: ["conflicts"] as const,
  candidate: (candidateId: number, includeInactive: boolean) =>
    ["conflicts", "candidate", candidateId, { includeInactive }] as const,
  registry: (params: ConflictRegistryParams) =>
    ["conflicts", "registry", params] as const,
};

export const CONFLICT_TYPE_LABELS: Record<ConflictType, string> = {
  blacklist: "Czarna lista klienta",
  current_employment: "Obecne zatrudnienie",
  nda: "NDA / cooling-off",
  competitor: "Klient konkurencyjny",
};

export const CONFLICT_TYPES: readonly ConflictType[] = [
  "blacklist",
  "nda",
  "competitor",
  "current_employment",
] as const;

/** Etykieta typu: najpierw ta z backendu, potem lokalna, na końcu surowy kod. */
export function conflictTypeLabel(
  row: Pick<ConflictRow, "type"> & { type_label?: string | null },
): string {
  return row.type_label || CONFLICT_TYPE_LABELS[row.type] || row.type;
}

/** Plakietka typu — wyłącznie tokeny (zero hardcoded palet). */
export const CONFLICT_TYPE_BADGE: Record<ConflictType, string> = {
  blacklist: "border-destructive/30 bg-destructive/10 text-destructive",
  current_employment: "border-info/30 bg-info-muted text-info-muted-foreground",
  nda: "border-warning/25 bg-warning-muted text-warning-muted-foreground",
  competitor: "border-border bg-muted text-muted-foreground",
};

export const CONFLICT_STATE_FILTER_LABELS: Record<
  ConflictRegistryStateFilter,
  string
> = {
  active: "Aktywne",
  expired: "Wygasłe",
  inactive: "Nieaktywne",
  all: "Wszystkie",
};

export const CONFLICT_STATE_LABELS: Record<ConflictState, string> = {
  active: "Aktywny",
  expired: "Wygasł",
  inactive: "Nieaktywny",
};

export const CONFLICT_STATE_BADGE: Record<ConflictState, string> = {
  active: "border-warning/25 bg-warning-muted text-warning-muted-foreground",
  expired: "border-border bg-muted text-muted-foreground",
  inactive: "border-border bg-muted text-muted-foreground",
};

/**
 * Stan wiersza. Backend liczy `state`; starszy backend go nie wysyła — wtedy
 * odtwarzamy go z `active` i `expires_at`.
 */
export function conflictState(
  row: Pick<ConflictRow, "active" | "expires_at"> & { state?: ConflictState | null },
  now: Date = new Date(),
): ConflictState {
  if (row.state) return row.state;
  if (!row.active) return "inactive";
  if (row.expires_at && new Date(row.expires_at).getTime() <= now.getTime()) {
    return "expired";
  }
  return "active";
}

/**
 * Plakietka dopuszczalności na wierszu listy (ranking, wyszukiwarka, podobne
 * rekrutacje). Zablokowane jest wyłącznie to, czego nie wolno przypisać
 * (weto hiring managera); konflikt z klientem to bursztynowe ostrzeżenie.
 */
export function eligibilityBadgeClass(
  eligibility: Pick<MatchEligibility, "assignment_allowed">,
): string {
  return eligibility.assignment_allowed === false
    ? "border border-destructive/30 bg-destructive/10 text-destructive"
    : "border border-warning/25 bg-warning-muted text-warning-muted-foreground";
}

const DATE_FMT = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Warsaw",
});

/** „01.10.2026" w strefie Europe/Warsaw; `null` dla pustej/niepoprawnej daty. */
export function formatConflictDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return DATE_FMT.format(d);
}

/** „wygasa 01.10.2026" / „wygasł 01.10.2026"; `null`, gdy brak daty. */
export function formatExpiry(
  expiresAt: string | null | undefined,
  now: Date = new Date(),
): string | null {
  const label = formatConflictDate(expiresAt);
  if (!label || !expiresAt) return null;
  const past = new Date(expiresAt).getTime() <= now.getTime();
  return `${past ? "wygasł" : "wygasa"} ${label}`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** Data lokalna jako wartość `<input type="date">` (RRRR-MM-DD). */
export function toDateInputValue(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Najwcześniejsza dozwolona data wygaśnięcia: jutro (lokalnie). */
export function minExpiryDateInput(now: Date = new Date()): string {
  const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return toDateInputValue(tomorrow);
}

function parseDateInput(value: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!m) return null;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const day = Number(m[3]);
  const d = new Date(y, mo - 1, day);
  if (d.getFullYear() !== y || d.getMonth() !== mo - 1 || d.getDate() !== day) {
    return null;
  }
  return d;
}

/**
 * `RRRR-MM-DD` z pola daty → pełne ISO końca tego dnia w strefie przeglądarki.
 * Konflikt „do 01.10" obowiązuje przez cały 1 października. `null` dla pustej
 * albo niepoprawnej wartości.
 */
export function expiresAtIso(dateInput: string | null | undefined): string | null {
  if (!dateInput) return null;
  const d = parseDateInput(dateInput);
  if (!d) return null;
  d.setHours(23, 59, 59, 999);
  return d.toISOString();
}

export interface ConflictFormValues {
  client_id: string;
  type: ConflictType;
  reason: string;
  /** Wartość `<input type="date">` (RRRR-MM-DD) albo pusty string. */
  expires_on: string;
}

export type ConflictFormErrors = Partial<Record<keyof ConflictFormValues, string>>;

/** Czysta walidacja formularza — te same zdania co odmowy backendu (422). */
export function validateConflictForm(
  values: ConflictFormValues,
  now: Date = new Date(),
): ConflictFormErrors {
  const errors: ConflictFormErrors = {};
  if (!values.client_id) errors.client_id = "Wybierz klienta.";
  const raw = values.expires_on.trim();
  if (!raw) {
    if (values.type === "nda") {
      errors.expires_on = "NDA wymaga daty wygaśnięcia.";
    }
  } else {
    const d = parseDateInput(raw);
    if (!d) {
      errors.expires_on = "Podaj poprawną datę wygaśnięcia.";
    } else if (toDateInputValue(d) < minExpiryDateInput(now)) {
      errors.expires_on = "Data wygaśnięcia musi być w przyszłości.";
    }
  }
  return errors;
}

export const DEACTIVATION_REASON_MIN = 3;

export function canSubmitDeactivation(reason: string): boolean {
  return reason.trim().length >= DEACTIVATION_REASON_MIN;
}
