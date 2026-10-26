/**
 * „W drodze” w Insights (22.10.2026) — teksty z odpowiedzi
 * `/api/insights/recruitment/in-flight` i `/in-flight/me`.
 *
 * Czyste funkcje: widoki tylko je rysują, a reguły („8–9”, nie „8,6”;
 * brak skuteczności = brak szacunku, nie zero) mają tu test.
 */

import type { InFlightColumn, InFlightResponse } from "@/lib/insights-api";
import { countPl } from "@/lib/plural-pl";

export function columnOf(
  columns: readonly InFlightColumn[],
  column: InFlightColumn["column"],
): InFlightColumn | null {
  return columns.find((c) => c.column === column) ?? null;
}

/** „ok. 8–9”, „ok. 9” albo `null`, gdy skuteczności jeszcze nie ma. */
export function forecastLabel(forecast: InFlightResponse["forecast"]): string | null {
  if (forecast.rate_pct === null || forecast.low === null || forecast.high === null) {
    return null;
  }
  return forecast.low === forecast.high
    ? `ok. ${forecast.low}`
    : `ok. ${forecast.low}–${forecast.high}`;
}

/**
 * Prognoza okresu: placementy już zrobione + szacunek z akceptacji („ok. 29–30”).
 * `null`, gdy szacunku jeszcze nie ma — wtedy pokazujemy same placementy.
 */
export function monthForecast(
  placements: number,
  forecast: InFlightResponse["forecast"],
): string | null {
  if (forecast.rate_pct === null || forecast.low === null || forecast.high === null) {
    return null;
  }
  const low = placements + forecast.low;
  const high = placements + forecast.high;
  return low === high ? `ok. ${low}` : `ok. ${low}–${high}`;
}

/**
 * Dopisek przy celu placementów zespołu (26.10.2026): cel sumuje tylko osoby
 * z tym celem, a lejek liczy całą firmę — bez dopisku 12 i 19 obok siebie
 * czytają się jak błąd.
 */
export function companyPlacementsNote(team: number, company: number): string {
  const outside = company - team;
  return outside > 0
    ? `W całej firmie: ${company} (${outside} poza celami osób).`
    : `W całej firmie: ${company}.`;
}

/** Zdanie o szacunku albo powód, dla którego go nie ma. */
export function forecastSentence(forecast: InFlightResponse["forecast"]): string {
  if (forecast.open === 0) return "Nie ma akceptacji do domknięcia.";
  const label = forecastLabel(forecast);
  if (label === null) {
    return `Szacunek placementów pojawi się po ${forecast.min_sample} rozstrzygniętych akceptacjach (jest ${forecast.resolved}).`;
  }
  return `Przy dotychczasowej skuteczności (${String(forecast.rate_pct).replace(".", ",")}%) to ${label} ${placementsWord(forecast.high ?? 0)}.`;
}

function placementsWord(n: number): string {
  return countPl(n, "placement", "placementy", "placementów").replace(/^\d+ /, "");
}

/** „Czekają od dziś”, „1 dzień”, „12 dni”. */
export function daysLabel(days: number): string {
  if (days <= 0) return "od dziś";
  return countPl(days, "dzień", "dni", "dni");
}

/**
 * Zdanie do podsumowania „Mój miesiąc”: co jeszcze może wpaść. `null`, gdy
 * nic nie stoi na rozmowie ani akceptacji — wtedy nie ma czego dopisywać.
 */
export function myInFlightSentence(columns: readonly InFlightColumn[]): string | null {
  const accepted = columnOf(columns, "contract")?.count ?? 0;
  const interviews = columnOf(columns, "client_interview")?.count ?? 0;
  const parts = [
    accepted > 0 ? countPl(accepted, "akceptację", "akceptacje", "akceptacji") : null,
    interviews > 0
      ? countPl(interviews, "rozmowę u klienta", "rozmowy u klienta", "rozmów u klienta")
      : null,
  ].filter((part): part is string => part !== null);
  if (parts.length === 0) return null;
  return `W drodze masz jeszcze ${parts.join(" i ")}.`;
}
