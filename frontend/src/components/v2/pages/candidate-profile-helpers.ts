/** Pure helpers for the candidate PROFILE view (CandidateDetailV2).
 *
 *  Companion to `candidate-list-helpers.ts` — these derive profile-specific
 *  display values (education list, language list, the scannable one-liner)
 *  from the loosely-typed candidate payload. Kept pure (no React/DOM) so they
 *  can be unit-tested in isolation. Reuses `getCurrentTitle` /
 *  `getExperienceLabel` from the list helpers to avoid duplicating coercion.
 */

import {
  formatCandidateLocation,
  getCurrentTitle,
  getExperienceLabel,
  type CandidateLite,
} from "@/components/v2/pages/candidate-list-helpers";

/** One education entry. Backend JSONB shape: {school, degree, field, year}. */
export interface EducationEntry {
  school?: string | null;
  degree?: string | null;
  field?: string | null;
  year?: string | number | null;
}

/** One language entry. Backend JSONB shape: {lang, level}. */
export interface LanguageEntry {
  lang: string;
  level?: string | null;
}

export interface CandidateProfileLite extends CandidateLite {
  education?: unknown;
  languages?: unknown;
  city?: string | null;
  location?: string | null;
  availability_status?: string | null;
}

/** Coerce the loosely-typed `education` payload to clean entries.
 *
 *  Accepts an array of {school, degree, field, year} objects. Drops entries
 *  that have neither a school nor a degree (nothing meaningful to show). */
export function getEducationList(c: CandidateProfileLite): EducationEntry[] {
  const raw = c.education;
  if (!Array.isArray(raw)) return [];
  const out: EducationEntry[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const obj = item as Record<string, unknown>;
    const entry: EducationEntry = {
      school: typeof obj.school === "string" ? obj.school.trim() : null,
      degree: typeof obj.degree === "string" ? obj.degree.trim() : null,
      field: typeof obj.field === "string" ? obj.field.trim() : null,
      year:
        typeof obj.year === "string" || typeof obj.year === "number"
          ? obj.year
          : null,
    };
    if (entry.school || entry.degree || entry.field) out.push(entry);
  }
  return out;
}

/** Coerce the loosely-typed `languages` payload to clean entries.
 *
 *  Accepts an array of {lang, level} objects OR plain strings ("English").
 *  Drops entries without a language name. */
export function getLanguageList(c: CandidateProfileLite): LanguageEntry[] {
  const raw = c.languages;
  if (!Array.isArray(raw)) return [];
  const out: LanguageEntry[] = [];
  for (const item of raw) {
    if (typeof item === "string") {
      const lang = item.trim();
      if (lang) out.push({ lang });
    } else if (item && typeof item === "object") {
      const obj = item as Record<string, unknown>;
      const lang =
        typeof obj.lang === "string"
          ? obj.lang.trim()
          : typeof obj.name === "string"
            ? obj.name.trim()
            : "";
      if (!lang) continue;
      const level = typeof obj.level === "string" ? obj.level.trim() : null;
      out.push({ lang, level: level || null });
    }
  }
  return out;
}

const _AVAILABILITY_LABEL: Record<string, string> = {
  actively_looking: "aktywnie szuka",
  open_to_offers: "otwarty na oferty",
  not_looking: "nie szuka",
};

/** Build a scannable one-line summary for the profile header.
 *
 *  Joins the available high-signal facts with " · ", skipping any segment
 *  that has no data:
 *    "Senior Python Developer · 7+ lat · Warszawa · otwarty na oferty"
 *
 *  Returns null when nothing meaningful is available, so the caller can fall
 *  back to the existing current_role line or render nothing. */
export function getCandidateSummaryLine(c: CandidateProfileLite): string | null {
  const segments: string[] = [];

  const title = getCurrentTitle(c);
  if (title) segments.push(title);

  const exp = getExperienceLabel(c.years_it_experience);
  if (exp) segments.push(exp.label);

  const loc = formatCandidateLocation(c.city ?? c.location ?? null);
  if (loc) segments.push(loc);

  const availability = c.availability_status
    ? _AVAILABILITY_LABEL[c.availability_status]
    : null;
  if (availability) segments.push(availability);

  return segments.length > 0 ? segments.join(" · ") : null;
}

const EXPERIENCE_CURRENT_WORDS = new Set([
  "present",
  "current",
  "obecnie",
  "teraz",
]);

/** Data wpisu doświadczenia w polskim zapisie — „07.2023”, „2019”, „obecnie”.
 *
 *  Wpisy z CV i z importów niosą różne zapisy („2023-07”, „2023-07-15”,
 *  „06.2023”, „present”). `formatDate` robiło z miesiąca pełną datę
 *  („1.07.2023”), a zapis nie-ISO wywracał render (`Invalid time value`).
 *  Nierozpoznany zapis wraca bez zmian — lepiej pokazać źródło niż zgadywać. */
export function formatExperienceDate(value: unknown): string {
  if (value == null) return "";
  const text = String(value).trim();
  if (!text) return "";
  if (EXPERIENCE_CURRENT_WORDS.has(text.toLowerCase())) return "obecnie";
  const iso = /^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?(?:T.*)?$/.exec(text);
  if (iso) return `${iso[2].padStart(2, "0")}.${iso[1]}`;
  return text;
}

export interface CvProjectionNotice {
  tone: "warning" | "info";
  text: string;
}

/** Czy wgrane CV zasiliło profil — sygnał dla sekcji „CV” (UAT M01-B01).
 *
 *  Bez tego profil z plikiem, który nie zasilił danych, wyglądał jak profil
 *  bez umiejętności: sekcje „Umiejętności”/„Doświadczenie” po prostu się nie
 *  renderowały. Dwa przypadki:
 *  - kwarantanna tożsamości — backend zostawia w `cv_extracted_data`
 *    znacznik `_identity_quarantine_source`, gdy imię i nazwisko w pliku
 *    należą do innej osoby (plik przestaje być głównym CV);
 *  - plik jest, a odczytu brak (`cv_parsed_at` puste) — w toku albo nieudany. */
export function getCvProjectionNotice(candidate: {
  cv_filename?: string | null;
  cv_parsed_at?: string | null;
  cv_extracted_data?: unknown;
}): CvProjectionNotice | null {
  const extracted =
    candidate.cv_extracted_data && typeof candidate.cv_extracted_data === "object"
      ? (candidate.cv_extracted_data as Record<string, unknown>)
      : {};
  if (extracted._identity_quarantine_source) {
    return {
      tone: "warning",
      text:
        "Wgrane CV nie zasiliło profilu: imię i nazwisko w dokumencie nie " +
        "zgadzają się z kandydatem. Plik zostaje w zakładce „Pliki i umowy”; " +
        "zwolnić go może administrator albo Head of Recruitment.",
    };
  }
  if (candidate.cv_filename && !candidate.cv_parsed_at) {
    return {
      tone: "info",
      text:
        "Dane z tego CV (umiejętności, doświadczenie) nie są jeszcze w " +
        "profilu. Świeżo wgrany plik odczytujemy zwykle w ciągu minuty — jeśli " +
        "nic się nie zmieni, odczyt się nie powiódł.",
    };
  }
  return null;
}
