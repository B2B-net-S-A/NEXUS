/**
 * Pure helpers that turn a job into a candidate-search prefill.
 *
 * Extracted from the job "Wyszukaj manualnie" tab so the mapping is unit
 * testable. Addresses the Phase-1 correctness containment findings:
 *
 * - SEARCH-P0-01: a job's rate is stored in ``salary_min/max`` but is *hourly*,
 *   so it must prefill ``rate_hourly_min/max`` (compared server-side against
 *   ``expected_rate_hourly``), NOT the monthly ``salary_min/max`` fields.
 * - SEARCH-P0-02: ``location`` is free text like ``"Warszawa / Remote"`` — it
 *   must be split into real cities with remote/hybrid tokens dropped, not
 *   passed whole as a single ``location_cities`` entry.
 * - SEARCH-P1-01: the reference number in the title (e.g. ``(ZOB-2846)``) must
 *   not pollute the free-text query, and ``nice_skills`` must NOT become a hard
 *   "at least one" gate (they are preferences; proper soft weighting is Phase 4).
 */

import type { CandidateSearchRequest } from "@/lib/candidate-search-api";

/** Minimal job shape needed to build a search prefill. */
export interface JobPrefillSource {
  title: string;
  must_skills?: unknown;
  nice_skills?: unknown;
  competence_category_id?: number | null;
  salary_min?: number | null;
  salary_max?: number | null;
  location?: string | null;
}

/**
 * Extract skill names from a JSONB skills value that may be a list of strings
 * or a list of ``{ name }`` objects. Caps at 10 to keep the query bounded.
 */
export function extractSkillNames(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((s) => {
      if (typeof s === "string") return s;
      if (s && typeof s === "object" && "name" in s) {
        const name = (s as { name?: unknown }).name;
        return typeof name === "string" ? name : null;
      }
      return null;
    })
    .filter((s): s is string => Boolean(s && s.trim()))
    .map((s) => s.trim())
    .slice(0, 10);
}

// A reference code inside brackets/parens, e.g. "(ZOB-2846)", "[REQ 12345]".
// Only strips groups that contain a digit so real parentheticals like
// "(Backend)" survive.
const BRACKETED_REF = /[([{][^)\]}]*\d[^)\]}]*[)\]}]/g;
// A standalone reference token, e.g. "ZOB-2846", "ZOB 2846", "REQ12345".
const STANDALONE_REF = /\b[A-Z]{2,}[-\s]?\d{2,}\b/g;
// Trailing separators left after stripping ("Title -", "Title ·").
const TRAILING_SEP = /[\s\-–—:·|,]+$/;

/**
 * Remove reference numbers from a job title so they don't leak into the
 * free-text query. Falls back to the trimmed original if stripping would
 * leave nothing.
 */
export function stripJobReference(title: string): string {
  const cleaned = title
    .replace(BRACKETED_REF, " ")
    .replace(STANDALONE_REF, " ")
    .replace(/\s+/g, " ")
    .replace(TRAILING_SEP, "")
    .trim();
  return cleaned || title.trim();
}

// Work-mode tokens that are NOT cities. Matched case-insensitively against a
// whole location segment (after splitting), so "Remote" / "Praca zdalna" /
// "hybryda" are dropped but a city named e.g. "Zdalna" (none exist) is unaffected.
const WORK_MODE_TOKENS = new Set([
  "remote",
  "zdalnie",
  "zdalna",
  "praca zdalna",
  "hybrid",
  "hybryda",
  "hybrydowo",
  "hybrydowa",
  "onsite",
  "on-site",
  "on site",
  "stacjonarnie",
  "stacjonarna",
  "elastyczny",
  "elastyczna",
  "flexible",
  "praca",
]);

/**
 * Split a free-text ``location`` into candidate cities, dropping work-mode
 * tokens. ``"Warszawa / Remote"`` → ``["Warszawa"]``; ``"Kraków, Wrocław"`` →
 * ``["Kraków", "Wrocław"]``. Dedupes case-insensitively, caps at 5.
 */
export function parseJobLocationCities(location?: string | null): string[] {
  if (!location) return [];
  const seen = new Set<string>();
  const cities: string[] = [];
  for (const part of location.split(/[/,;|\n]+/)) {
    const city = part.trim();
    if (!city) continue;
    if (WORK_MODE_TOKENS.has(city.toLowerCase())) continue;
    const key = city.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    cities.push(city);
    if (cities.length >= 5) break;
  }
  return cities;
}

/**
 * Build the candidate-search prefill for a job's manual-search tab.
 *
 * Note ``nice_skills`` are deliberately omitted: they used to be sent as
 * ``skills_any`` which the backend turns into a mandatory "at least one" gate,
 * zeroing out results. Proper soft-preference weighting lands in Phase 4.
 */
export function buildJobSearchPrefill(
  job: JobPrefillSource,
): Partial<CandidateSearchRequest> {
  return {
    q: stripJobReference(job.title),
    competence_category_ids: job.competence_category_id
      ? [job.competence_category_id]
      : [],
    skills_must: extractSkillNames(job.must_skills),
    rate_hourly_min: job.salary_min ?? null,
    rate_hourly_max: job.salary_max ?? null,
    location_cities: parseJobLocationCities(job.location),
    sort: "relevance",
  };
}
