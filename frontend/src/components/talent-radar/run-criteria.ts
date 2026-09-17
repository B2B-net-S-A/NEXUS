/**
 * Kryteria biegu Talent Radaru i walidacja liczb formularza.
 *
 * Czysty moduł (bez Reacta i API) — testowalny bez montowania ciężkiego
 * `TalentRadarWorkspace`.
 */

/** Limity lustrzane do `TalentRadarSearchRequest` w `backend/app/api/talent_radar.py`. */
export const RADAR_BUDGET_MAX = 2000;
export const RADAR_OFFICE_DAYS_MAX = 7;

export const RADAR_BUDGET_ERROR = `Budżet PLN/h musi być liczbą od 1 do ${RADAR_BUDGET_MAX} (puste pole = bez sufitu).`;
export const RADAR_OFFICE_DAYS_ERROR = `Dni w biurze / tydzień: liczba całkowita od 0 do ${RADAR_OFFICE_DAYS_MAX}.`;

/**
 * Błąd pola budżetu albo `null`. Puste pole i `0` to „bez sufitu" (formularz
 * nie wysyła wtedy budżetu), więc nie są błędem. Bez tej walidacji wartość
 * spoza zakresu kończyła się 422 po angielsku z backendu.
 */
export function radarBudgetError(raw: string): string | null {
  const value = raw.trim();
  if (value === "") return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0 || parsed > RADAR_BUDGET_MAX) {
    return RADAR_BUDGET_ERROR;
  }
  return null;
}

/** Błąd pola dni w biurze albo `null`. `0` jest LEGALNE („tylko zdalnie"). */
export function radarOfficeDaysError(raw: string): string | null {
  const value = raw.trim();
  if (value === "") return null;
  const parsed = Number(value);
  if (
    !Number.isInteger(parsed) ||
    parsed < 0 ||
    parsed > RADAR_OFFICE_DAYS_MAX
  ) {
    return RADAR_OFFICE_DAYS_ERROR;
  }
  return null;
}

/**
 * Kryteria, z którymi uruchomiono wyświetlany bieg. Zapisywane w chwili
 * startu, bo odpowiedź przeglądu niesie wyłącznie budżet i listy wymagań —
 * a wyniki bez kryteriów nie mówią, dla jakiego klienta i jakich warunków
 * zostały policzone.
 */
export interface RadarRunCriteria {
  clientName: string;
  budget: number | null;
  location: string | null;
  officeDays: number | null;
  officeLocation: string | null;
  excludeRemoteOnly: boolean;
}

export function isRadarRunCriteria(value: unknown): value is RadarRunCriteria {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const v = value as Record<string, unknown>;
  const numberOrNull = (x: unknown) => x === null || typeof x === "number";
  const stringOrNull = (x: unknown) => x === null || typeof x === "string";
  return (
    typeof v.clientName === "string" &&
    numberOrNull(v.budget) &&
    stringOrNull(v.location) &&
    numberOrNull(v.officeDays) &&
    stringOrNull(v.officeLocation) &&
    typeof v.excludeRemoteOnly === "boolean"
  );
}

/**
 * Jedna linia „Kryteria biegu". `serverBudget` (z odpowiedzi przeglądu)
 * wygrywa z budżetem zapamiętanym przy starcie — to budżet, który naprawdę
 * zastosowano.
 */
export function formatRadarRunCriteria(
  criteria: RadarRunCriteria,
  serverBudget?: number | null,
): string {
  const budget = serverBudget ?? criteria.budget;
  const parts = [
    `Klient: ${criteria.clientName}`,
    budget ? `budżet do ${budget} PLN/h` : "bez sufitu stawki",
  ];
  if (criteria.location) parts.push(`lokalizacja: ${criteria.location}`);
  if (criteria.officeDays !== null) {
    parts.push(
      criteria.officeDays === 0
        ? "tylko zdalnie"
        : `biuro ${criteria.officeDays} dni/tydz.${criteria.officeLocation ? ` (${criteria.officeLocation})` : ""}`,
    );
  } else if (criteria.officeLocation) {
    parts.push(`miasto biura: ${criteria.officeLocation}`);
  }
  if (criteria.excludeRemoteOnly) parts.push("bez „wyłącznie zdalnie”");
  return parts.join(" · ");
}
