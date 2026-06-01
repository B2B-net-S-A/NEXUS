/** Pure helpers for the candidate PROFILE view (CandidateDetailV2).
 *
 *  Companion to `candidate-list-helpers.ts` – these derive profile-specific
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
  // Detail endpoint exposes salary as expected_salary/currency (hero stat tile
  // reads these); the list endpoint uses salary_expectation. Accept both.
  expected_salary?: number | null;
  salary_expectation?: number | null;
  currency?: string | null;
  salary_currency?: string | null;
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

/** Format an expected-salary value as a compact "20k PLN" style string. */
function _formatSalary(c: CandidateProfileLite): string | null {
  const value = c.expected_salary ?? c.salary_expectation ?? null;
  if (value == null || value <= 0) return null;
  const currency = c.currency ?? c.salary_currency ?? "PLN";
  const k = value >= 1000 ? `${Math.round(value / 1000)}k` : String(value);
  return `${k} ${currency}`;
}

/** Build a scannable one-line summary for the profile header.
 *
 *  Joins the available high-signal facts with " · ", skipping any segment
 *  that has no data:
 *    "Senior Python Developer · 7+ lat · Warszawa · 20k PLN · otwarty na oferty"
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

  const salary = _formatSalary(c);
  if (salary) segments.push(salary);

  const availability = c.availability_status
    ? _AVAILABILITY_LABEL[c.availability_status]
    : null;
  if (availability) segments.push(availability);

  return segments.length > 0 ? segments.join(" · ") : null;
}
