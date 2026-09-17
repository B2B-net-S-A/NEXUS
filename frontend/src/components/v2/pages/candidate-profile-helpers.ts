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

/** One education entry. Backend JSONB shape: {school, degree, field, year}.
 *  Odczyt CV v7 dokłada `start_year`/`end_year`. */
export interface EducationEntry {
  school?: string | null;
  degree?: string | null;
  field?: string | null;
  year?: string | number | null;
  startYear?: number | null;
  endYear?: number | null;
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
      ...(typeof obj.start_year === "number" ? { startYear: obj.start_year } : {}),
      ...(typeof obj.end_year === "number" ? { endYear: obj.end_year } : {}),
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
  /** `not_parsed` = plik jest, danych brak — profil proponuje ponowny odczyt (UAT B12). */
  kind: "quarantine" | "not_parsed";
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
      kind: "quarantine",
      text:
        "Wgrane CV nie zasiliło profilu: imię i nazwisko w dokumencie nie " +
        "zgadzają się z kandydatem. Plik zostaje w zakładce „Pliki i umowy”; " +
        "zwolnić go może administrator albo Head of Recruitment.",
    };
  }
  if (candidate.cv_filename && !candidate.cv_parsed_at) {
    return {
      tone: "info",
      kind: "not_parsed",
      text:
        "Dane z tego CV (umiejętności, doświadczenie) nie są jeszcze w " +
        "profilu. Świeżo wgrany plik odczytujemy zwykle w ciągu minuty — jeśli " +
        "nic się nie zmieni, odczyt się nie powiódł (np. plik jest skanem) " +
        "albo plik przyszedł z importu bez odczytu. Możesz uruchomić odczyt ponownie.",
    };
  }
  return null;
}


/** Lata wykształcenia do wyświetlenia: „2011–2016”, „2016” albo pusty tekst. */
export function formatEducationYears(entry: EducationEntry): string {
  if (entry.startYear && entry.endYear) return `${entry.startYear}–${entry.endYear}`;
  if (entry.endYear) return String(entry.endYear);
  if (entry.year != null && String(entry.year).trim()) return String(entry.year);
  if (entry.startYear) return `od ${entry.startYear}`;
  return "";
}

const EMPLOYMENT_TYPE_LABEL: Record<string, string> = {
  b2b: "B2B",
  employment: "umowa o pracę",
  contract: "umowa cywilnoprawna",
  internship: "staż",
  freelance: "freelance",
};

/** Szczegóły stanowiska z odczytu CV v7. Stare wpisy dają puste wartości. */
export function getExperienceDetails(entry: unknown): {
  technologies: string[];
  employmentType: string | null;
  client: string | null;
} {
  const obj =
    entry && typeof entry === "object" ? (entry as Record<string, unknown>) : {};
  const technologies = Array.isArray(obj.technologies)
    ? obj.technologies
        .filter((t): t is string => typeof t === "string" && t.trim() !== "")
        .map((t) => t.trim())
    : [];
  const employmentType =
    typeof obj.employment_type === "string"
      ? (EMPLOYMENT_TYPE_LABEL[obj.employment_type] ?? null)
      : null;
  const client =
    typeof obj.client === "string" && obj.client.trim() ? obj.client.trim() : null;
  return { technologies, employmentType, client };
}

export interface CertificationEntry {
  name: string;
  issuer: string | null;
  year: number | null;
  expires: string | null;
}

export interface ProjectEntry {
  name: string;
  role: string | null;
  company: string | null;
  technologies: string[];
  start: string | null;
  end: string | null;
  description: string | null;
}

export interface SkillTimelineEntry {
  skill: string;
  firstUsed: string | null;
  lastUsed: string | null;
  months: number | null;
  isCurrent: boolean;
  contexts: string[];
}

export interface RichCvProfile {
  certifications: CertificationEntry[];
  projects: ProjectEntry[];
  achievements: string[];
  timeline: SkillTimelineEntry[];
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** Pełny profil z odczytu CV v7 albo null dla profili sprzed zmiany.
 *
 *  null jest znaczący: stary odczyt nie pytał o certyfikaty ani projekty, więc
 *  pusta sekcja „Certyfikaty” twierdziłaby, że CV ich nie zawiera. */
export function getRichCvProfile(candidate: {
  cv_extracted_data?: unknown;
}): RichCvProfile | null {
  const extracted =
    candidate.cv_extracted_data && typeof candidate.cv_extracted_data === "object"
      ? (candidate.cv_extracted_data as Record<string, unknown>)
      : null;
  if (!extracted || Number(extracted._profile_schema ?? 0) < 2) return null;
  const list = (key: string): Record<string, unknown>[] =>
    Array.isArray(extracted[key])
      ? (extracted[key] as unknown[]).filter(
          (x): x is Record<string, unknown> => !!x && typeof x === "object",
        )
      : [];
  return {
    certifications: list("certifications")
      .map((c) => ({
        name: str(c.name) ?? "",
        issuer: str(c.issuer),
        year: typeof c.year === "number" ? c.year : null,
        expires: str(c.expires),
      }))
      .filter((c) => c.name),
    projects: list("projects")
      .map((p) => ({
        name: str(p.name) ?? "",
        role: str(p.role),
        company: str(p.company),
        technologies: Array.isArray(p.technologies)
          ? (p.technologies as unknown[]).filter(
              (t): t is string => typeof t === "string" && t.trim() !== "",
            )
          : [],
        start: str(p.start),
        end: str(p.end),
        description: str(p.description),
      }))
      .filter((p) => p.name),
    achievements: Array.isArray(extracted.achievements)
      ? (extracted.achievements as unknown[]).filter(
          (a): a is string => typeof a === "string" && a.trim() !== "",
        )
      : [],
    timeline: list("skill_timeline")
      .map((t) => ({
        skill: str(t.skill) ?? "",
        firstUsed: str(t.first_used),
        lastUsed: str(t.last_used),
        months: typeof t.months === "number" ? t.months : null,
        isCurrent: t.is_current === true,
        contexts: Array.isArray(t.contexts)
          ? (t.contexts as unknown[])
              .map((ctx) =>
                ctx && typeof ctx === "object"
                  ? str((ctx as Record<string, unknown>).company)
                  : null,
              )
              .filter((x): x is string => !!x)
          : [],
      }))
      .filter((t) => t.skill),
  };
}

/** „4 lata 7 mies.”, „11 mies.” albo pusty tekst, gdy CV nie daje długości. */
export function formatUsageMonths(months: number | null): string {
  if (!months || months <= 0) return "";
  const years = Math.floor(months / 12);
  const rest = months % 12;
  const yearLabel =
    years === 1 ? "rok" : years % 10 >= 2 && years % 10 <= 4 && (years % 100 < 10 || years % 100 >= 20) ? "lata" : "lat";
  const parts: string[] = [];
  if (years > 0) parts.push(`${years} ${yearLabel}`);
  if (rest > 0) parts.push(`${rest} mies.`);
  return parts.join(" ");
}
