/**
 * Karta dojazdu kandydata (wariant D, decyzja Artura 27.11.2026): do jakich
 * biur dojedzie, czy dojedzie okazjonalnie do innego miasta, przeprowadzka
 * i skąd to wiemy. Klucze w `preferences` zapisuje serwer przy odrzuceniu
 * „Lokalizacja lub tryb pracy” → „Za daleko do biura” (`office_cities`,
 * `occasional_commute`, `relocation`, `commute_source`); `office_cities`
 * wypełnia też ankieta „Twoje warunki”.
 */

import { formatDayMonthPl } from "@/lib/date-pl";

export interface CommuteRelocation {
  willing: boolean;
  targets: string[];
}

export interface CommutePreferences {
  officeCities: string[];
  /** `true` — raz w miesiącu do innego miasta tak; `null` — nie pytano. */
  occasionalCommute: boolean | null;
  relocation: CommuteRelocation | null;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function cityList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((v): v is string => typeof v === "string")
    .map((v) => v.trim())
    .filter(Boolean);
}

export function commutePreferences(preferences: unknown): CommutePreferences {
  const prefs = record(preferences);
  const relocation = record(prefs.relocation);
  return {
    officeCities: cityList(prefs.office_cities),
    occasionalCommute:
      typeof prefs.occasional_commute === "boolean" ? prefs.occasional_commute : null,
    relocation:
      typeof relocation.willing === "boolean"
        ? { willing: relocation.willing, targets: cityList(relocation.targets) }
        : null,
  };
}

/** „inne miasto: raz w miesiącu” / „inne miasto: nie”; `null` — nie pytano. */
export function occasionalCommuteLine(value: boolean | null): string | null {
  if (value === null) return null;
  return value ? "inne miasto: raz w miesiącu" : "inne miasto: nie";
}

/** „nie”, „tak”, „tak: Wrocław”; `null` — nie pytano. */
export function relocationLine(value: CommuteRelocation | null): string | null {
  if (!value) return null;
  if (!value.willing) return "nie";
  return value.targets.length ? `tak: ${value.targets.join(", ")}` : "tak";
}

/** „z odrzucenia 27.11 · Senior QA” — tylko przy źródle z odrzucenia. */
export function commuteSourceLine(preferences: unknown): string | null {
  const source = record(record(preferences).commute_source);
  if (source.source !== "rejection") return null;
  const date = typeof source.at === "string" ? formatDayMonthPl(source.at) : "—";
  const title =
    typeof source.job_title === "string" && source.job_title.trim()
      ? source.job_title.trim()
      : null;
  return [date === "—" ? "z odrzucenia" : `z odrzucenia ${date}`, title]
    .filter(Boolean)
    .join(" · ");
}

/** Porównanie nazw miast bez wielkości liter i białych znaków. */
export function sameCity(a: string | null | undefined, b: string | null | undefined): boolean {
  return (a ?? "").trim().toLocaleLowerCase("pl") === (b ?? "").trim().toLocaleLowerCase("pl");
}

/** Dopisuje miasto do listy bez powtórek; `null`, gdy nie ma czego dodać. */
export function addCity(list: readonly string[], city: string, max: number): string[] | null {
  const name = city.trim().slice(0, 120);
  if (!name || list.length >= max || list.some((c) => sameCity(c, name))) return null;
  return [...list, name];
}
