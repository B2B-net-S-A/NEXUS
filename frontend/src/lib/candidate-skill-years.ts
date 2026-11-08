/**
 * „Lata z technologią” (08.11.2026, wariant B wybrany przez Artura):
 * „Java · co najmniej 3 lata” na liście kandydatów.
 *
 * Lata liczy serwer z dat stanowisk i projektów w CV, przy których CV wymienia
 * technologię (`candidate_skill_usage.months`). Osoba z technologią, ale bez
 * dat, zostaje na końcu listy z `unknown_fields: ["skill_years"]`, chyba że
 * `hideUnknownSkillYears`. Na drucie: `skill_years=Java:3` (powtarzany),
 * w adresie `sky=Java:3|Kafka:2` i `husy=1`.
 */

export interface SkillYearsRow {
  skill: string;
  years: number;
}

/** Wpis serwera przy wierszu listy (`CandidateSkillYears`). */
export interface CandidateSkillYears {
  skill: string;
  years_min: number;
  months: number | null;
  source: "cv_roles" | "manual" | null;
}

export const SKILL_YEARS_MAX_ROWS = 5;
export const SKILL_YEARS_MIN = 1;
export const SKILL_YEARS_MAX = 30;

export const NO_SKILL_YEARS_FILTER = {
  skillYears: [] as string[],
  hideUnknownSkillYears: false,
};

const clampYears = (n: number): number =>
  Math.min(SKILL_YEARS_MAX, Math.max(SKILL_YEARS_MIN, Math.round(n)));

/** „Java:3” → wiersz; zły zapis → `null` (adres z ręki, stary link). */
export function parseSkillYearsEntry(raw: string): SkillYearsRow | null {
  const at = raw.lastIndexOf(":");
  if (at <= 0) return null;
  const skill = raw.slice(0, at).split(/\s+/).filter(Boolean).join(" ");
  const years = Number.parseInt(raw.slice(at + 1).trim(), 10);
  if (!skill || skill.length > 120 || !Number.isFinite(years)) return null;
  if (years < SKILL_YEARS_MIN || years > SKILL_YEARS_MAX) return null;
  return { skill, years };
}

export function formatSkillYearsEntry(row: SkillYearsRow): string {
  return `${row.skill.trim()}:${clampYears(row.years)}`;
}

/**
 * Wpisy z adresu → wiersze bez złych i bez powtórzeń (ta sama technologia
 * bez wielkości liter = wyższy próg, jak serwer), najwyżej 5.
 */
export function parseSkillYearsEntries(values: readonly string[]): SkillYearsRow[] {
  const out = new Map<string, SkillYearsRow>();
  for (const value of values) {
    const row = parseSkillYearsEntry(value);
    if (!row) continue;
    const key = row.skill.toLocaleLowerCase("pl-PL");
    const prev = out.get(key);
    out.set(key, prev ? { skill: prev.skill, years: Math.max(prev.years, row.years) } : row);
  }
  return Array.from(out.values()).slice(0, SKILL_YEARS_MAX_ROWS);
}

/** Wiersze z okienka (także niedokończone) → wpisy do adresu i API. */
export function skillYearsEntries(rows: readonly SkillYearsRow[]): string[] {
  return parseSkillYearsEntries(
    rows.filter((r) => r.skill.trim()).map((r) => formatSkillYearsEntry(r)),
  ).map(formatSkillYearsEntry);
}

function plural(n: number, one: string, few: string, many: string): string {
  if (n === 1) return one;
  const mod10 = n % 10;
  const mod100 = n % 100;
  return mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? few : many;
}

/** „rok” / „lata” / „lat” po liczbie. */
export function yearsUnit(n: number): string {
  return plural(n, "rok", "lata", "lat");
}

/** „1 rok”, „3 lata”, „5 lat”, „22 lata”. */
export function yearsWord(n: number): string {
  return `${n} ${yearsUnit(n)}`;
}

/** 80 → „6 lat 8 mies.”, 7 → „7 mies.”, 24 → „2 lata”. */
export function formatMonths(months: number): string {
  const years = Math.floor(months / 12);
  const rest = months % 12;
  if (years === 0) return `${rest} mies.`;
  return rest ? `${yearsWord(years)} ${rest} mies.` : yearsWord(years);
}

/** „Java ≥ 3 lata” — chip i pigułka. */
export function skillYearsRowLabel(row: SkillYearsRow): string {
  return `${row.skill} ≥ ${yearsWord(row.years)}`;
}

/** Lata przy wierszu listy, które warto pokazać (z datami w CV). */
export function knownSkillYears(
  entries: readonly CandidateSkillYears[] | null | undefined,
): Array<{ skill: string; text: string }> {
  return (entries ?? [])
    .filter((e): e is CandidateSkillYears & { months: number } => e.months != null)
    .map((e) => ({ skill: e.skill, text: formatMonths(e.months) }));
}

/** Technologie z filtru, przy których CV tej osoby nie podaje dat. */
export function missingSkillYears(
  entries: readonly CandidateSkillYears[] | null | undefined,
): string[] {
  return (entries ?? []).filter((e) => e.months == null).map((e) => e.skill);
}
