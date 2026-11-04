/**
 * Pure helpers that turn a job into a candidate-search prefill.
 *
 * Extracted from the job "Wyszukaj manualnie" tab so the mapping is unit
 * testable. Addresses the Phase-1 correctness containment findings:
 *
 * - Candidate-profile rate policy: ``salary_min/max`` belongs to the job
 *   budget while ``expected_rate_hourly`` is an immutable B2B PLN net/hour
 *   candidate fact. The job fields do not carry a safe, typed unit contract,
 *   so they must never prefill ``rate_hourly_min/max`` or be converted.
 * - SEARCH-P0-02: ``location`` is free text like ``"Warszawa / Remote"`` — it
 *   must be split into real cities with remote/hybrid tokens dropped, not
 *   passed whole as a single ``location_cities`` entry.
 * - SEARCH-P1-01: the reference number in the title (e.g. ``(ZOB-2846)``) must
 *   not pollute the free-text query, and ``nice_skills`` must NOT become a hard
 *   "at least one" gate (they are preferences; proper soft weighting is Phase 4).
 *   The flip side of that same finding: the prefill was also *too poor* — it
 *   carried only the bare title, dropping the job's ``description`` /
 *   ``requirements`` / ``seniority``. Those now feed the free-text query, routed
 *   through ``search_mode: "hybrid"`` so the text drives semantic
 *   (BM25 + dense + rerank) retrieval instead of a boolean ``AND`` over
 *   ``websearch_to_tsquery`` — enriching recall without re-introducing a hard
 *   gate. Signals with no NULL-safe home are deliberately NOT mapped: a job has
 *   no candidate-facing ``languages`` / ``notice_period`` / start-date field to
 *   source from, the search request has no remote-policy filter, and
 *   ``experience_years_min`` hard-excludes candidates whose experience is
 *   unknown — so seniority is carried in the semantic text, not as a cut.
 */

import type { CandidateSearchRequest } from "@/lib/candidate-search-api";

/** Minimal job shape needed to build a search prefill. */
export interface JobPrefillSource {
  title: string;
  /** Free-text role description — enriches the semantic query. */
  description?: string | null;
  /** Free-text requirements (often a concise skills list) — dense signal. */
  requirements?: string | null;
  /** Seniority enum: junior | mid | senior | lead | architect. */
  seniority?: string | null;
  must_skills?: unknown;
  nice_skills?: unknown;
  competence_category_id?: number | null;
  salary_min?: number | null;
  salary_max?: number | null;
  location?: string | null;
  /** `remote` = praca w pełni zdalna — miasto oferty nie jest wtedy filtrem. */
  remote_policy?: string | null;
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

// The backend caps the free-text `q` at 500 chars; stay under it with room to
// spare and truncate on a word boundary so we never send a half-word lexeme.
const MAX_QUERY_CHARS = 480;

/**
 * Clean a free-text job fragment (``description`` / ``requirements``) for use
 * inside the search query: strip reference codes, drop HTML tags, and collapse
 * all whitespace/markup runs into single spaces. Returns "" for empty input.
 */
export function cleanQueryFragment(raw?: string | null): string {
  if (!raw) return "";
  return raw
    .replace(/<[^>]+>/g, " ") // any stray HTML tags
    .replace(BRACKETED_REF, " ")
    .replace(STANDALONE_REF, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Truncate to ``max`` chars without cutting a word in half. */
function truncateOnWordBoundary(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  return (lastSpace > max * 0.6 ? cut.slice(0, lastSpace) : cut).trim();
}

/**
 * Assemble the free-text search query for a job. Combines the ref-stripped
 * title, the seniority token, and cleaned ``requirements`` + ``description`` —
 * so the job's real signal (not just its title) reaches the semantic query.
 * Ordered most-informative-first so truncation drops the least useful tail.
 * Reference numbers never leak in (both the title and the fragments are
 * ref-stripped). Falls back to the bare title if enrichment is empty.
 */
export function buildJobSearchQueryText(job: JobPrefillSource): string {
  const title = stripJobReference(job.title);
  const seniority = job.seniority ? String(job.seniority).trim() : "";
  const combined = [
    title,
    seniority,
    cleanQueryFragment(job.requirements),
    cleanQueryFragment(job.description),
  ]
    .filter((part) => part.length > 0)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  return truncateOnWordBoundary(combined, MAX_QUERY_CHARS) || title;
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
// „Warszawa lub okolice", „Kraków i okolica", „Gdańsk + okolice (hybrydowo)":
// dopisek o okolicy i nawiasy nie są nazwą miasta — dosłowne „Warszawa lub
// okolice" nie pasowało do żadnego kandydata (test manualny 21.09.2026).
// Kraj i adres to nie miasto. „Polska (lokalizacja obowiązkowa)” szła jako
// filtr miasta „Polska” i wycinała 91% osób, które zespół wybrał do takich
// rekrutacji (audyt 26.09.2026); „ul. Chmielna 89” nie pasuje do nikogo.
const COUNTRY_TOKENS = new Set([
  "polska",
  "cała polska",
  "cala polska",
  "poland",
  "pl",
  "europa",
  "europe",
  "ue",
  "eu",
]);
const ADDRESS_PART = /^(?:ul|al|pl|os)\.?\s|\d/i;
const NEARBY_SUFFIX = /\s*(?:(?:lub|i|oraz|albo|\+|&)\s*)?okolic[aey]?\b.*$/i;
const PARENTHETICAL = /\([^)]*\)/g;
// Alternatywy zapisane słowami („Warszawa lub Kraków") to kilka miast.
const CITY_ALTERNATIVE = /\s+(?:lub|albo|oraz|i|or)\s+/i;

export function parseJobLocationCities(location?: string | null): string[] {
  if (!location) return [];
  const seen = new Set<string>();
  const cities: string[] = [];
  const parts = location
    .replace(PARENTHETICAL, " ")
    .split(/[/,;|\n]+/)
    .map((part) => part.replace(NEARBY_SUFFIX, ""))
    .flatMap((part) => part.split(CITY_ALTERNATIVE));
  for (const part of parts) {
    const city = part.trim();
    if (!city) continue;
    if (WORK_MODE_TOKENS.has(city.toLowerCase())) continue;
    if (COUNTRY_TOKENS.has(city.toLowerCase())) continue;
    if (ADDRESS_PART.test(city)) continue;
    const key = city.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    cities.push(city);
    if (cities.length >= 5) break;
  }
  return cities;
}

/** Nazwa oferty do pola wyszukiwania: tytuł bez numeru referencyjnego +
 *  seniority. Opis i wymagania ZOSTAJĄ poza polem (przegląd UX 17.09.2026):
 *  kilkaset znaków prozy w polu „szukaj" wyglądało jak zepsuty formularz,
 *  a sygnał wymagań niesie już `skills_must`. */
// „PKO BP: Programista Java Senior", „Nordea: BCCM …" — prefiks klienta przed
// dwukropkiem to nie stanowisko; w polu wyszukiwania kierował ranking na nazwę
// banku. Najwyżej trzy słowa, żeby nie ciąć tytułów typu „Rola: specjalizacja"
// z dłuższym początkiem.
const CLIENT_PREFIX = /^\s*[^:]{1,40}?:\s+(?=\S)/;

function stripClientPrefix(title: string): string {
  const match = CLIENT_PREFIX.exec(title);
  if (!match) return title;
  const prefix = match[0].replace(/:\s*$/, "").trim();
  if (prefix.split(/\s+/).length > 3) return title;
  const rest = title.slice(match[0].length).trim();
  return rest || title;
}

export function buildJobSearchTitleQuery(job: JobPrefillSource): string {
  const title = stripClientPrefix(stripJobReference(job.title));
  const seniority = job.seniority ? String(job.seniority).trim() : "";
  return [title, seniority].filter((part) => part.length > 0).join(" ").trim();
}

// Grupa zapisana jako „java lub kotlin" (etykieta `requirementLabels`) to kilka
// alternatywnych technologii — do rankingu idzie każda z nich osobno.
const ALTERNATIVE_SEPARATOR = /\s+(?:lub|albo|or)\s+/i;

/** Wymagania obowiązkowe do `skills_must`: zapisane wymagania rekrutacji
 *  (`mustLabels`) wygrywają; bez nich — kolumna `must_skills`, ale wyłącznie
 *  pozycje do trzech słów (kolumna bywa prozą, a zdanie nie jest nazwą
 *  technologii). */
export function jobMustSkillNames(
  job: JobPrefillSource,
  mustLabels?: readonly string[] | null,
): string[] {
  const fromLabels = (mustLabels ?? [])
    .flatMap((label) => label.split(ALTERNATIVE_SEPARATOR))
    .map((s) => s.trim())
    .filter(Boolean);
  const source =
    fromLabels.length > 0
      ? fromLabels
      : extractSkillNames(job.must_skills).filter(
          (name) => name.split(/\s+/).length <= 3,
        );
  const seen = new Set<string>();
  const out: string[] = [];
  for (const name of source) {
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(name);
    if (out.length >= 10) break;
  }
  return out;
}

/**
 * Build the candidate-search prefill for a job's manual-search tab.
 *
 * The free-text ``q`` is the ref-stripped title + seniority only (UX review
 * 17.09.2026 — description prose in the search box read as a broken form) and
 * rides ``search_mode: "hybrid"``. Requirements reach the search through
 * ``skills_must`` (saved matching requirements, see ``jobMustSkillNames``).
 * ``buildJobSearchQueryText`` stays available for callers that want the full
 * enriched text.
 *
 * ``nice_skills`` are omitted for historical reasons: they used to be sent as
 * ``skills_any`` back when the backend turned that into a mandatory "at least
 * one" gate, which zeroed out results. That gate is GONE — since SEARCH-P0-03
 * both ``skills_must`` and ``skills_any`` are merged into one ranking signal
 * (``skills_soft_rank``) and neither can cut a candidate from the result set.
 * Sending ``nice_skills`` here is therefore safe again and would only improve
 * ordering; it stays out only because that is a product decision about prefill
 * behaviour, not a constraint of the search API. Do not re-add the old warning.
 * ``languages`` / ``notice_period_max`` / ``availability_date_before`` /
 * ``experience_years_min`` are intentionally NOT set here — a job has no
 * NULL-safe source/target for them, so setting them would invent a hard filter
 * the finding explicitly warns against.
 */
export function buildJobSearchPrefill(
  job: JobPrefillSource,
  mustLabels?: readonly string[] | null,
): Partial<CandidateSearchRequest> {
  return {
    q: buildJobSearchTitleQuery(job) || stripJobReference(job.title),
    // `q` from the title stays recall-safe under hybrid retrieval; in the
    // default boolean mode `q` becomes a hard `websearch_to_tsquery` AND.
    search_mode: "hybrid",
    competence_category_ids: job.competence_category_id
      ? [job.competence_category_id]
      : [],
    skills_must: jobMustSkillNames(job, mustLabels),
    // Praca w pełni zdalna: miasto z oferty nie może zawężać kandydatów.
    location_cities:
      job.remote_policy === "remote" ? [] : parseJobLocationCities(job.location),
    sort: "relevance",
  };
}
