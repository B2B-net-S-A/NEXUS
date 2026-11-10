/**
 * Filtry wyników zespołu: rola i klient (decyzja Artura z 10.11.2026, prośby
 * Olafa z 09.11.2026). Jedna reguła dla pulpitu „Aktywność rekrutacyjna”,
 * listy „Kto się liczy”, tabeli „Ludzie” w Insights → Zespół, kafla „Wyniki
 * zespołu” i raportu „Aktywność zespołu”. Kto należy do grupy, liczy serwer
 * (`backend/app/services/team_filters.py`); opis w
 * `docs/claude/finanse-insights/filtry-rola-i-klient.md`.
 */

export type TeamRoleFilter = "recruiter" | "delivery_lead" | "all"

export const TEAM_ROLE_OPTIONS: { value: TeamRoleFilter; label: string }[] = [
  { value: "recruiter", label: "Rekruterzy" },
  { value: "delivery_lead", label: "Delivery Leadzi" },
  { value: "all", label: "Wszyscy" },
]

/** Parametry zapytania — to, co rozumie serwer. */
export interface TeamFilterParams {
  role: TeamRoleFilter
  /** Klient rekrutacji; `null` = wszyscy klienci. */
  clientId: number | null
}

export interface TeamFilters extends TeamFilterParams {
  /** Nazwa wybranego klienta do nagłówka i listy, gdy go nie ma w okresie. */
  clientName: string | null
}

/** Pulpit i kafel „Wyniki zespołu”: rekruterzy, wszyscy klienci. */
export const DEFAULT_TEAM_FILTERS: TeamFilters = {
  role: "recruiter",
  clientId: null,
  clientName: null,
}

/**
 * Lista otwarta z liczby lejka całej firmy: wszyscy, żeby lista zgadzała się
 * z klikniętą liczbą. Filtr można zawęzić na liście.
 */
export const ALL_TEAM_FILTERS: TeamFilters = { role: "all", clientId: null, clientName: null }

export interface ClientOption {
  id: number
  name: string
  count: number
}

export function isFiltered(filters: TeamFilterParams): boolean {
  return filters.role !== "all" || filters.clientId !== null
}

/** Parametry zapytania; domyślne wartości nie idą w adresie. */
export function teamFilterQuery(
  filters: TeamFilterParams | undefined,
): { role?: TeamRoleFilter; client_id?: number } {
  if (!filters) return {}
  return {
    ...(filters.role !== "all" ? { role: filters.role } : {}),
    ...(filters.clientId !== null ? { client_id: filters.clientId } : {}),
  }
}

export function roleLabel(role: TeamRoleFilter): string {
  return TEAM_ROLE_OPTIONS.find((option) => option.value === role)?.label ?? role
}

/** „Rekruterzy · Nordea Bank Abp” — do nagłówka; pusty napis bez filtra. */
export function describeTeamFilters(filters: TeamFilters): string {
  return [filters.role === "all" ? null : roleLabel(filters.role), filters.clientName]
    .filter(Boolean)
    .join(" · ")
}

const ROLES = new Set<string>(TEAM_ROLE_OPTIONS.map((option) => option.value))

export function parseStoredTeamFilters(raw: string | null): TeamFilters | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<TeamFilters>
    if (typeof value.role !== "string" || !ROLES.has(value.role)) return null
    const clientId =
      typeof value.clientId === "number" && Number.isInteger(value.clientId) && value.clientId > 0
        ? value.clientId
        : null
    return {
      role: value.role as TeamRoleFilter,
      clientId,
      clientName: clientId !== null && typeof value.clientName === "string" ? value.clientName : null,
    }
  } catch {
    return null
  }
}

/** Wybór pamięta przeglądarka, jak okres na pasku (bez zapisu do układu pulpitu). */
export function readStoredTeamFilters(key: string): TeamFilters | null {
  try {
    return parseStoredTeamFilters(window.localStorage.getItem(key))
  } catch {
    return null
  }
}

export function writeStoredTeamFilters(key: string, value: TeamFilters): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // Prywatne okno albo zablokowana pamięć — filtr działa do odświeżenia strony.
  }
}
