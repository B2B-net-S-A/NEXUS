/**
 * Candidate search URL filter state — single source of truth.
 *
 * Every filter in `CandidatesListV2` round-trips through `encodeFilters` /
 * `decodeFilters`. Saved searches store the encoded querystring, so adding
 * new fields to `CandidateFilters` is backward-compatible — `decodeFilters`
 * ignores unknown params and fills unknown fields with defaults.
 */

import {
  parseSkillExpression,
  serializeSkillBuckets,
} from "@/lib/skill-expression";
import type { OpenToValue } from "@/lib/filter-options";
import { normalizeLanguageFilters } from "@/lib/candidate-languages";

export type SortMode = "newest" | "oldest" | "name" | "relevance";
/** Jak czytać tekst `q` — `auto` = decyduje backend („Rozumiem to jako…"). */
export type TextModeFilter = "auto" | "literal" | "semantic";
export type SkillCombine = "and" | "or";
export type RemoteMode = "remote" | "hybrid" | "onsite";
export type CandidatesView = "list" | "tiles";
export type RecruitmentMatch = "assigned" | "not_assigned";
export type RecentlyChangedJobs = 1 | 2 | 3 | null;

export type CandidateStatusFilter = "active" | "passive" | "blacklisted";
export type EmploymentFilter = "at_client" | "available";
export type AvailabilityFilter =
  | "actively_looking"
  | "open_to_offers"
  | "not_looking"
  | "unknown";
export type PipelineStageFilter =
  | "posting"
  | "new"
  | "prep_call"
  | "screening"
  | "verified"
  | "interview"
  | "cv_sent"
  | "client_interview"
  | "acceptance"
  | "negotiation"
  | "onboarding"
  | "hired"
  | "rejected"
  | "withdrawn";

const CANDIDATE_STATUS_VALUES: ReadonlySet<string> = new Set([
  "active",
  "passive",
  "blacklisted",
]);
const EMPLOYMENT_VALUES: ReadonlySet<string> = new Set(["at_client", "available"]);
const AVAILABILITY_VALUES: ReadonlySet<string> = new Set([
  "actively_looking",
  "open_to_offers",
  "not_looking",
  "unknown",
]);
const PIPELINE_STAGE_VALUES: ReadonlySet<string> = new Set([
  "posting",
  "new",
  "prep_call",
  "screening",
  "verified",
  "interview",
  "cv_sent",
  "client_interview",
  "acceptance",
  "negotiation",
  "onboarding",
  "hired",
  "rejected",
  "withdrawn",
]);

export interface CandidateFilters {
  q: string;
  status: CandidateStatusFilter[];
  employment: EmploymentFilter[];
  availability: AvailabilityFilter[];
  pipelineStage: PipelineStageFilter[];
  // Competence-category ids (the 5 NEXUS CCs). A candidate matches when the
  // category is their PRIMARY or a SECONDARY assignment. Round-trips as `cc`.
  competenceCategoryIds: number[];
  sort: SortMode;
  /**
   * Czy rekruter JAWNIE wybrał „Najnowsi". Bez wyboru sortowania lista z
   * wpisanym tekstem szereguje po trafności (`sort=relevance` w API); dopiero
   * świadome „Najnowsi" to wyłącza. Znaczenie ma wyłącznie dla `newest` —
   * każde inne sortowanie jest wyborem z definicji. W URL: `sort=newest`.
   */
  sortExplicit: boolean;
  /** Tryb tekstu (`text_mode` w API) — w URL `tm`, pomijany przy `auto`. */
  textMode: TextModeFilter;
  /**
   * Języki: `kod` albo `kod:POZIOM` (np. `en:B2`), każdy wymagany. W URL `lang`
   * (CSV), w API powtarzany `languages`.
   */
  languages: string[];
  page: number;
  remote: RemoteMode[];
  // Boolean skill expression typed into the "Umiejętności" box, e.g.
  // `Python AND React OR Vue -PHP`. Parsed into skill-scoped must/any/none
  // buckets at API time (see `filtersToApiParams` + `skill-expression.ts`).
  // Empty string = no skill filter. Round-trips in the URL as `skills_q`.
  // Semantyka v2 (decyzja 21.09.2026): pozycje dodatnie = „Musi mieć" (twardo,
  // `a|b`/`OR` = którakolwiek z grupy), NOT = „Wyklucz" (twardo).
  skillsExpr: string;
  // „Mile widziane" — trzeci kubełek: tylko kolejność, nikogo nie usuwa.
  // Pozycja może być grupą `a|b`. W URL powtarzany parametr `skills_pref`.
  skillsPreferred: string[];
  // „Ukryj osoby bez danych" (`hide_unknown`) — bez tego osoby bez lokalizacji,
  // stażu albo stawki zostają z plakietką `unknown_fields`. W URL `hu=1`.
  hideUnknown: boolean;
  location: string;
  poolIds: number[];
  addedByIds: number[];
  currentCompany: string[];
  pastCompany: string[];
  currentTitle: string[];
  workedAtClientIds: number[];
  // Przynależność do rekrutacji — kandydaci przypisani (lub NIE) do wybranych
  // rekrutacji (job ids). `recruitmentMatch` decyduje o kierunku: `assigned`
  // (jest w pipeline którejkolwiek z wybranych) lub `not_assigned` (w żadnej).
  // Pusta lista = filtr nieaktywny (tryb bez znaczenia). Round-trips w URL jako
  // `recr` (CSV ids) + `recr_mode` (zapisywane tylko dla `not_assigned`).
  recruitmentIds: number[];
  recruitmentMatch: RecruitmentMatch;
  // Lata doświadczenia — inclusive numeric band (years of IT experience).
  // `null` on either side means that bound is open. The backend matches against
  // a derived per-candidate interval (exact `years_it_experience` or the coarse
  // Traffit bucket) using range-overlap, so a candidate counts when their
  // experience could fall inside [min, max].
  experienceMin: number | null;
  experienceMax: number | null;
  // Oczekiwana stawka godzinowa (B2B, PLN/h) — inclusive numeric band. `null`
  // on either side = open bound. Backend matches `expected_rate_hourly` with
  // range bounds, excluding candidates with no rate (exclusive of nulls, like
  // salary/experience). Round-trips in the URL as `rate_min`/`rate_max`.
  rateMin: number | null;
  rateMax: number | null;
  // Stage-move filters — "kto dodał na etap i kiedy". Correlated with
  // `pipelineStage` on the backend (the matched stage move's mover + date).
  // `stageMovedByIds` mirrors `added_by`'s sentinel: `0` = system/Traffit import
  // (CandidateStage.moved_by IS NULL). Dates are `YYYY-MM-DD` (inclusive bounds).
  stageMovedByIds: number[];
  stageMovedAfter: string;
  stageMovedBefore: string;
  // Client that owns the job on which the matched stage move happened
  // (`Job.client_id` via `CandidateStage.job_id`). Correlated with the same
  // move as `stageMovedByIds`/dates — distinct from `workedAtClientIds`
  // (hired/contract history). Joins the move-filter family → triggers
  // historical matching unless `stageCurrentOnly` is on.
  stageClientIds: number[];
  // "Data wysłania do klienta" — filtr po dacie rekomendacji kandydata do
  // klienta (przejście na etap `cv_sent`). Inclusive `YYYY-MM-DD` bounds,
  // HISTORYCZNY (dowolne wysłanie w oknie, niezależnie od bieżącego etapu) i
  // niezależny od rodziny `stage*`. Empty string = bound open. Round-trips in
  // the URL as `sent_from`/`sent_to`.
  sentToClientFrom: string;
  sentToClientTo: string;
  // "Aktualny etap" toggle. When true → force CURRENT-stage matching even with
  // who/when/client move-filters (sends `stage_current_only=true`). When false
  // (default) → omit the param so the backend auto-resolves: current for a bare
  // stage chip, historical as soon as a move-filter is present.
  stageCurrentOnly: boolean;
  // Deklarowana otwartość na dodatkowe formy współpracy. W URL
  // canonical zapisujemy CSV, natomiast dekoder przyjmuje też powtarzane
  // `open_to` (stare linki/API tooling).
  openTo: OpenToValue[];
  // Zmiana pracodawcy wykryta przez synchronizację LinkedIn: 1/2/3 miesiące.
  recentlyChangedJobs: RecentlyChangedJobs;
  /**
   * Wersja semantyki filtrów → `semantics_version` w API. Domyślnie 2 (jedna
   * semantyka z wyszukiwarką, decyzja 21.09.2026) — także dla starych zakładek
   * bez `sv`. `1` (`sv=1`) niesie wyłącznie zapis przypięty do dawnych zasad
   * („Zostaw po staremu" po migracji), żeby lista pokazała zbiór jego alertu.
   */
  semanticsVersion: 1 | 2;
  view: CandidatesView;
  savedSearchId: number | null;
  // Traffit-style advanced search buckets. Each phrase matches ILIKE
  // across name/email/CV/ai_summary/competence_category/experience/skills/tags.
  qAll: string[]; // every phrase must match (AND)
  // ANY bucket = list of OR-groups that AND together. Each inner array is one
  // OR-group (phrases OR'd); groups AND with each other. `[["a","b"],["c"]]`
  // means `(a OR b) AND c`. A single group is the classic "any of these" and
  // round-trips from legacy `?q_any=a|b` URLs (decoded as one group).
  qAny: string[][];
  qNone: string[]; // none of these phrases may match (NOT)
}

export const DEFAULT_FILTERS: CandidateFilters = {
  q: "",
  status: [],
  employment: [],
  availability: [],
  pipelineStage: [],
  competenceCategoryIds: [],
  sort: "newest",
  sortExplicit: false,
  textMode: "auto",
  languages: [],
  page: 1,
  remote: [],
  skillsExpr: "",
  skillsPreferred: [],
  hideUnknown: false,
  location: "",
  poolIds: [],
  addedByIds: [],
  currentCompany: [],
  pastCompany: [],
  currentTitle: [],
  workedAtClientIds: [],
  recruitmentIds: [],
  recruitmentMatch: "assigned",
  experienceMin: null,
  experienceMax: null,
  rateMin: null,
  rateMax: null,
  stageMovedByIds: [],
  stageMovedAfter: "",
  stageMovedBefore: "",
  stageClientIds: [],
  sentToClientFrom: "",
  sentToClientTo: "",
  stageCurrentOnly: false,
  openTo: [],
  recentlyChangedJobs: null,
  semanticsVersion: 2,
  view: "list",
  savedSearchId: null,
  qAll: [],
  qAny: [],
  qNone: [],
};

const CSV = (xs: Array<string | number>): string => xs.join(",");
const parseCsv = (raw: string | null): string[] =>
  raw ? raw.split(",").map((x) => x.trim()).filter(Boolean) : [];
const parseCsvInt = (raw: string | null): number[] =>
  parseCsv(raw)
    .map((x) => Number.parseInt(x, 10))
    .filter((n) => Number.isFinite(n));

// Single non-negative integer bound (years of experience), clamped to [0, 60].
// Returns null for missing/garbage so a malformed URL param can't leak a bogus
// value into the API call — mirrors `parseIsoDate`'s defensive stance.
export const parseYearBound = (raw: string | null): number | null => {
  if (raw == null || raw === "") return null;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n) || n < 0) return null;
  return Math.min(n, 60);
};

// Single non-negative integer bound (expected hourly rate, PLN/h), clamped to
// [0, 100000]. Same defensive stance as `parseYearBound`, but no tight upper
// cap — hourly rates run to the hundreds, so the ceiling only blocks garbage.
export const parseRateBound = (raw: string | null): number | null => {
  if (raw == null || raw === "") return null;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n) || n < 0) return null;
  return Math.min(n, 100_000);
};

// Pipe-separated list — used for company/title values that may contain commas
// (e.g. "Intel, Inc."). Safer than comma for free-text inputs.
const PIPE = (xs: string[]): string => xs.join("|");
const parsePipe = (raw: string | null): string[] =>
  raw ? raw.split("|").map((x) => x.trim()).filter(Boolean) : [];

// `YYYY-MM-DD` calendar date — what <input type="date"> emits and what the
// backend's `date` query params expect. Reject anything else so a malformed
// URL param can't leak a bogus value into the API call.
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const parseIsoDate = (raw: string | null): string =>
  raw && ISO_DATE.test(raw) ? raw : "";

// Skill boolean expression. New URLs carry `skills_q` verbatim. Legacy URLs /
// saved searches stored a flat `skills` CSV plus a `skill_combine` of `and`/`or`
// — reconstruct an equivalent expression (`a AND b` / `a OR b`) so old shares
// keep working. Multi-word legacy skills are quoted so re-parsing is stable.
export const decodeSkillsExpr = (sp: URLSearchParams): string => {
  const direct = sp.get("skills_q");
  if (direct && direct.trim()) return direct.trim();
  const legacy = parseCsv(sp.get("skills"));
  if (!legacy.length) return "";
  return (sp.get("skill_combine") ?? "").trim().toLowerCase() === "or"
    ? serializeSkillBuckets({ must: [], anyGroups: [legacy], none: [] })
    : serializeSkillBuckets({ must: legacy, anyGroups: [], none: [] });
};

export function encodeFilters(f: CandidateFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.status.length) p.set("status", CSV(f.status));
  if (f.employment.length) p.set("employment", CSV(f.employment));
  if (f.availability.length) p.set("availability", CSV(f.availability));
  if (f.pipelineStage.length) p.set("stage", CSV(f.pipelineStage));
  if (f.competenceCategoryIds.length) p.set("cc", CSV(f.competenceCategoryIds));
  if (f.sort !== "newest" || f.sortExplicit) p.set("sort", f.sort);
  if (f.textMode !== "auto") p.set("tm", f.textMode);
  const languages = normalizeLanguageFilters(f.languages);
  if (languages.length) p.set("lang", CSV(languages));
  if (f.page > 1) p.set("page", String(f.page));
  if (f.remote.length) p.set("remote", CSV(f.remote));
  if (f.skillsExpr.trim()) p.set("skills_q", f.skillsExpr.trim());
  for (const entry of f.skillsPreferred) {
    if (entry.trim()) p.append("skills_pref", entry.trim());
  }
  if (f.hideUnknown) p.set("hu", "1");
  if (f.location) p.set("loc", f.location);
  if (f.poolIds.length) p.set("pool", CSV(f.poolIds));
  if (f.addedByIds.length) p.set("added_by", CSV(f.addedByIds));
  if (f.currentCompany.length) p.set("cur_co", PIPE(f.currentCompany));
  if (f.pastCompany.length) p.set("past_co", PIPE(f.pastCompany));
  if (f.currentTitle.length) p.set("title", PIPE(f.currentTitle));
  if (f.workedAtClientIds.length) p.set("client_hist", CSV(f.workedAtClientIds));
  if (f.recruitmentIds.length) {
    p.set("recr", CSV(f.recruitmentIds));
    if (f.recruitmentMatch !== "assigned") p.set("recr_mode", f.recruitmentMatch);
  }
  if (f.experienceMin !== null) p.set("exp_min", String(f.experienceMin));
  if (f.experienceMax !== null) p.set("exp_max", String(f.experienceMax));
  if (f.rateMin !== null) p.set("rate_min", String(f.rateMin));
  if (f.rateMax !== null) p.set("rate_max", String(f.rateMax));
  if (f.stageMovedByIds.length) p.set("stage_by", CSV(f.stageMovedByIds));
  if (f.stageMovedAfter) p.set("stage_from", f.stageMovedAfter);
  if (f.stageMovedBefore) p.set("stage_to", f.stageMovedBefore);
  if (f.stageClientIds.length) p.set("stage_client", CSV(f.stageClientIds));
  if (f.sentToClientFrom) p.set("sent_from", f.sentToClientFrom);
  if (f.sentToClientTo) p.set("sent_to", f.sentToClientTo);
  if (f.stageCurrentOnly) p.set("stage_current", "1");
  if (f.openTo.length) p.set("open_to", CSV(f.openTo));
  if (f.recentlyChangedJobs !== null) {
    p.set("rcj", String(f.recentlyChangedJobs));
  }
  // v2 jest domyślne — `sv` w adresie tylko dla zapisu przypiętego do v1.
  if (f.semanticsVersion === 1) p.set("sv", "1");
  if (f.qAll.length) p.set("q_all", PIPE(f.qAll));
  // One repeated `q_any` param per OR-group (each pipe-joined). Empty groups
  // are skipped. Legacy single-param `?q_any=a|b` decodes back to one group.
  for (const group of f.qAny) {
    if (group.length) p.append("q_any", PIPE(group));
  }
  if (f.qNone.length) p.set("q_none", PIPE(f.qNone));
  if (f.view !== "list") p.set("view", f.view);
  if (f.savedSearchId !== null) p.set("ss", String(f.savedSearchId));
  return p;
}

export function decodeFilters(sp: URLSearchParams): CandidateFilters {
  const sortRaw = sp.get("sort");
  const sort: SortMode =
    sortRaw === "oldest" || sortRaw === "name" || sortRaw === "relevance"
      ? sortRaw
      : "newest";
  const tmRaw = sp.get("tm");
  const textMode: TextModeFilter =
    tmRaw === "literal" || tmRaw === "semantic" ? tmRaw : "auto";
  const viewRaw = sp.get("view");
  const view: CandidatesView = viewRaw === "tiles" ? "tiles" : "list";
  const remote = parseCsv(sp.get("remote")).filter(
    (v): v is RemoteMode => v === "remote" || v === "hybrid" || v === "onsite"
  );
  // Backward-compat: legacy URLs persisted `status` as a single value (no CSV).
  // `parseCsv` happily handles both — single value yields a 1-element array.
  const status = parseCsv(sp.get("status")).filter(
    (v): v is CandidateStatusFilter => CANDIDATE_STATUS_VALUES.has(v),
  );
  const employment = parseCsv(sp.get("employment")).filter(
    (v): v is EmploymentFilter => EMPLOYMENT_VALUES.has(v),
  );
  const availability = parseCsv(sp.get("availability")).filter(
    (v): v is AvailabilityFilter => AVAILABILITY_VALUES.has(v),
  );
  const pipelineStage = parseCsv(sp.get("stage")).filter(
    (v): v is PipelineStageFilter => PIPELINE_STAGE_VALUES.has(v),
  );
  const pageRaw = Number.parseInt(sp.get("page") ?? "1", 10);
  const page = Number.isFinite(pageRaw) && pageRaw > 0 ? pageRaw : 1;
  const ssRaw = sp.get("ss");
  const ssNum = ssRaw !== null ? Number.parseInt(ssRaw, 10) : NaN;
  const savedSearchId = Number.isFinite(ssNum) && ssNum > 0 ? ssNum : null;
  const openTo = sp
    .getAll("open_to")
    .flatMap((raw) => parseCsv(raw))
    .filter(
      (value): value is OpenToValue =>
        value === "side_projects" ||
        value === "sales_support" ||
        value === "expert_consult",
    );
  const rcjRaw = Number.parseInt(sp.get("rcj") ?? "", 10);
  const recentlyChangedJobs: RecentlyChangedJobs =
    rcjRaw === 1 || rcjRaw === 2 || rcjRaw === 3 ? rcjRaw : null;
  return {
    q: sp.get("q") ?? "",
    status,
    employment,
    availability,
    pipelineStage,
    competenceCategoryIds: parseCsvInt(sp.get("cc")),
    sort,
    sortExplicit: sort === "newest" && sortRaw === "newest",
    textMode,
    languages: normalizeLanguageFilters(parseCsv(sp.get("lang"))),
    page,
    remote,
    skillsExpr: decodeSkillsExpr(sp),
    skillsPreferred: sp
      .getAll("skills_pref")
      .map((x) => x.trim())
      .filter(Boolean),
    hideUnknown: sp.get("hu") === "1",
    location: sp.get("loc") ?? "",
    poolIds: parseCsvInt(sp.get("pool")),
    addedByIds: parseCsvInt(sp.get("added_by")),
    currentCompany: parsePipe(sp.get("cur_co")),
    pastCompany: parsePipe(sp.get("past_co")),
    currentTitle: parsePipe(sp.get("title")),
    workedAtClientIds: parseCsvInt(sp.get("client_hist")),
    recruitmentIds: parseCsvInt(sp.get("recr")),
    recruitmentMatch:
      sp.get("recr_mode") === "not_assigned" ? "not_assigned" : "assigned",
    experienceMin: parseYearBound(sp.get("exp_min")),
    experienceMax: parseYearBound(sp.get("exp_max")),
    rateMin: parseRateBound(sp.get("rate_min")),
    rateMax: parseRateBound(sp.get("rate_max")),
    stageMovedByIds: parseCsvInt(sp.get("stage_by")),
    stageMovedAfter: parseIsoDate(sp.get("stage_from")),
    stageMovedBefore: parseIsoDate(sp.get("stage_to")),
    stageClientIds: parseCsvInt(sp.get("stage_client")),
    sentToClientFrom: parseIsoDate(sp.get("sent_from")),
    sentToClientTo: parseIsoDate(sp.get("sent_to")),
    stageCurrentOnly: sp.get("stage_current") === "1",
    openTo,
    recentlyChangedJobs,
    // Brak `sv` (stare zakładki, zapisy) = v2 — zamierzone (21.09.2026).
    semanticsVersion: sp.get("sv") === "1" ? 1 : 2,
    view,
    savedSearchId,
    qAll: parsePipe(sp.get("q_all")),
    // Each repeated `q_any` value is one pipe-joined OR-group. Drop empties.
    qAny: sp.getAll("q_any").map(parsePipe).filter((g) => g.length > 0),
    qNone: parsePipe(sp.get("q_none")),
  };
}

export function filtersEqual(a: CandidateFilters, b: CandidateFilters): boolean {
  return encodeFilters(a).toString() === encodeFilters(b).toString();
}

// ── Navigation context (next/prev candidate from filtered list) ──────────────

/**
 * Encode `CandidateFilters` plus 1-based position into URLSearchParams so a
 * full-page candidate profile (`/candidates/[id]?nav=search&pos=N&...`) can
 * reconstruct the filtered list it belongs to and offer prev/next nav.
 *
 * Reuses `encodeFilters` for filter serialization.
 */
export function encodeNavContext(
  filters: CandidateFilters,
  position: number,
): URLSearchParams {
  const p = encodeFilters(filters);
  p.set("nav", "search");
  p.set("pos", String(Math.max(1, Math.floor(position))));
  return p;
}

/**
 * Decode nav context from URLSearchParams. Returns `null` if `nav` is not set
 * (i.e., the profile was opened without nav context — show no prev/next UI).
 */
export function decodeNavContext(
  sp: URLSearchParams,
): { filters: CandidateFilters; position: number } | null {
  if (sp.get("nav") !== "search") return null;
  const posRaw = Number.parseInt(sp.get("pos") ?? "", 10);
  const position = Number.isFinite(posRaw) && posRaw > 0 ? posRaw : 1;
  return { filters: decodeFilters(sp), position };
}

/**
 * Encode a "came from this recruitment" back-reference so a candidate profile
 * opened from a job's pipeline (`/candidates/[id]?from=job&jobId=N`) can offer a
 * "back to recruitment" link instead of the default "back to candidates".
 *
 * Orthogonal to `encodeNavContext` (prev/next over a filtered list) — a profile
 * opened from a job has no list to page through, only an origin to return to.
 */
export function encodeJobBackRef(jobId: number): URLSearchParams {
  const p = new URLSearchParams();
  p.set("from", "job");
  p.set("jobId", String(jobId));
  return p;
}

/**
 * Decode the job back-reference. Returns the origin job id when `from=job` with
 * a valid positive `jobId`, else `null`.
 */
export function decodeJobBackRef(sp: URLSearchParams): number | null {
  if (sp.get("from") !== "job") return null;
  const jid = Number.parseInt(sp.get("jobId") ?? "", 10);
  return Number.isFinite(jid) && jid > 0 ? jid : null;
}

/**
 * Encode a "came from Talent Radar" back-reference (`?from=talent-radar`) so a
 * candidate profile opened from radar results offers "back to Talent Radar"
 * instead of the default "back to candidates".
 *
 * The URL carries only WHERE to go back — never the query state. The radar
 * page restores the search itself from sessionStorage
 * (lib/talent-radar-session.ts); radar request text runs up to 20k chars, so
 * it has no business being in a URL.
 */
export function encodeTalentRadarBackRef(): URLSearchParams {
  const p = new URLSearchParams();
  p.set("from", "talent-radar");
  return p;
}

/**
 * Decode the Talent Radar back-reference. Mutually exclusive with
 * `decodeJobBackRef` by construction — `from` is a single parameter.
 */
export function decodeTalentRadarBackRef(sp: URLSearchParams): boolean {
  return sp.get("from") === "talent-radar";
}

/**
 * Map `CandidateFilters` to the `params` object accepted by axios `.get` for
 * `GET /api/candidates`. Mirrors the exact param mapping in `CandidatesListV2`
 * so navigation queries hit the same react-query cache key as the list view.
 *
 * Pass `extras` for fields the list view sends that aren't part of
 * `CandidateFilters` proper (e.g. `include_match_stats`, `match_threshold`).
 */
export function filtersToApiParams(
  filters: CandidateFilters,
  page: number,
  extras: Record<string, unknown> = {},
): Record<string, unknown> {
  // Parse the boolean skill expression into skill-scoped buckets.
  // v2: jawne kubełki — `must` → `skills_required`, `anyGroups` → powtarzane
  // `skills_required_any_groups` (`a|b`), `none` → `skills_excluded`,
  // „Mile widziane" → `skills_preferred`.
  // v1 (zapis przypięty do dawnych zasad): pola legacy jak dotąd — `must` →
  // `skills` (AND, lowercase `skill_combine`), `anyGroups` → `skills_any`,
  // `none` → `skills_none`.
  const skillBuckets = parseSkillExpression(filters.skillsExpr);
  const v2 = filters.semanticsVersion !== 1;
  const anyGroups = skillBuckets.anyGroups.length
    ? skillBuckets.anyGroups.map((g) => g.join("|"))
    : undefined;
  const hasText = filters.q.trim().length >= 2;
  const languages = normalizeLanguageFilters(filters.languages);
  return {
    // Poniżej 2 znaków NIE wysyłamy `q` — backend odpowiada wtedy 422
    // (`min_length=2`, jak `/api/search/global`), a pole filtruje się przecież
    // w trakcie pisania: pierwsza litera nie może dawać czerwonego błędu.
    // Do 09.2026 backend po cichu pomijał taki filtr i zwracał CAŁĄ bazę
    // (62 243 kandydatów) z kodem 200 — stąd i 422 po tamtej stronie, i ten
    // guard po tej.
    q: filters.q.trim().length >= 2 ? filters.q : undefined,
    status: filters.status.length ? filters.status : undefined,
    // Tryb tekstu tylko przy tekście i we wspólnej semantyce (v1 go nie zna).
    text_mode: hasText && v2 ? filters.textMode : undefined,
    page,
    sort: effectiveSort(filters) || undefined,
    languages: languages.length ? languages : undefined,
    skills: !v2 && skillBuckets.must.length ? skillBuckets.must : undefined,
    skill_combine: !v2 && skillBuckets.must.length > 1 ? "and" : undefined,
    skills_any: v2 ? undefined : anyGroups,
    skills_none: !v2 && skillBuckets.none.length ? skillBuckets.none : undefined,
    skills_required: v2 && skillBuckets.must.length ? skillBuckets.must : undefined,
    skills_required_any_groups: v2 ? anyGroups : undefined,
    skills_excluded: v2 && skillBuckets.none.length ? skillBuckets.none : undefined,
    skills_preferred: filters.skillsPreferred.length
      ? filters.skillsPreferred
      : undefined,
    hide_unknown: filters.hideUnknown ? true : undefined,
    remote_policy: filters.remote.length ? filters.remote : undefined,
    employment: filters.employment.length ? filters.employment : undefined,
    availability: filters.availability.length ? filters.availability : undefined,
    pipeline_stage: filters.pipelineStage.length ? filters.pipelineStage : undefined,
    competence_category_id: filters.competenceCategoryIds.length
      ? filters.competenceCategoryIds
      : undefined,
    location: filters.location || undefined,
    talent_pool_id: filters.poolIds.length ? filters.poolIds : undefined,
    added_by_user_id: filters.addedByIds.length ? filters.addedByIds : undefined,
    current_company: filters.currentCompany.length ? filters.currentCompany : undefined,
    past_company: filters.pastCompany.length ? filters.pastCompany : undefined,
    current_title: filters.currentTitle.length ? filters.currentTitle : undefined,
    worked_at_client_id: filters.workedAtClientIds.length
      ? filters.workedAtClientIds
      : undefined,
    recruitment_id: filters.recruitmentIds.length
      ? filters.recruitmentIds
      : undefined,
    // Mode only matters with a selection, and only `not_assigned` flips the
    // default — omit otherwise so the API call stays minimal.
    recruitment_match:
      filters.recruitmentIds.length && filters.recruitmentMatch !== "assigned"
        ? filters.recruitmentMatch
        : undefined,
    min_experience: filters.experienceMin ?? undefined,
    max_experience: filters.experienceMax ?? undefined,
    min_rate: filters.rateMin ?? undefined,
    max_rate: filters.rateMax ?? undefined,
    stage_moved_by: filters.stageMovedByIds.length
      ? filters.stageMovedByIds
      : undefined,
    stage_moved_after: filters.stageMovedAfter || undefined,
    stage_moved_before: filters.stageMovedBefore || undefined,
    stage_client_id: filters.stageClientIds.length
      ? filters.stageClientIds
      : undefined,
    sent_to_client_from: filters.sentToClientFrom || undefined,
    sent_to_client_to: filters.sentToClientTo || undefined,
    // Only send when forcing current-stage matching; omitting lets the backend
    // auto-resolve (current for a bare stage, historical with a move-filter).
    stage_current_only: filters.stageCurrentOnly ? true : undefined,
    open_to: filters.openTo.length ? filters.openTo : undefined,
    recently_changed_jobs: filters.recentlyChangedJobs ?? undefined,
    semantics_version: filters.semanticsVersion,
    q_all: filters.qAll.length ? filters.qAll : undefined,
    // ANY OR-groups → one repeated `q_any_group` value per group (pipe-joined).
    q_any_group: filters.qAny.some((g) => g.length)
      ? filters.qAny.filter((g) => g.length).map((g) => g.join("|"))
      : undefined,
    q_none: filters.qNone.length ? filters.qNone : undefined,
    ...extras,
  };
}

/**
 * Sortowanie wysyłane do API. Wpisany tekst bez jawnego wyboru sortowania =
 * trafność (dla wyszukiwania po znaczeniu to kolejność puli; decyzja
 * 22.09.2026). Jawny wybór rekrutera wygrywa zawsze.
 */
export function effectiveSort(filters: Pick<CandidateFilters, "q" | "sort" | "sortExplicit">): SortMode {
  const hasText = filters.q.trim().length >= 2;
  if (hasText && filters.sort === "newest" && !filters.sortExplicit) return "relevance";
  return filters.sort;
}

/**
 * Parametry `GET /api/candidates` wspólne z wyszukiwarką
 * (`POST /api/search/candidates`) — jedna semantyka filtrów w obu silnikach
 * (backend: `app/services/candidate_search_predicates.py`). `filtersToApiParams`
 * wysyła kubełki umiejętności, `hide_unknown` i `semantics_version`; pola
 * legacy tylko dla zapisu przypiętego do v1.
 */
export interface CandidateListSharedFilterParams {
  /** „Musi mieć" — twardo, każda; pozycja może być grupą `a|b`. */
  skills_required?: string[];
  /** Grupy „którakolwiek" — powtarzany parametr, każda wartość `a|b`. */
  skills_required_any_groups?: string[];
  /** „Mile widziane" — tylko ranking. */
  skills_preferred?: string[];
  /** „Wyklucz" — twardo. */
  skills_excluded?: string[];
  /** Tagi — cały tag, każdy wymagany. */
  tags?: string[];
  /** Kody ISO krajów — którykolwiek. */
  country?: string[];
  /** Kilka miast naraz (którekolwiek) — kształt wyszukiwarki. */
  location_cities?: string[];
  text_mode?: "auto" | "literal" | "semantic";
  /** Ukryj osoby bez danych dla aktywnych filtrów lokalizacji/stażu/stawki. */
  hide_unknown?: boolean;
  /** Brak = dotychczasowe wyniki listy (v1); 2 = semantyka wspólna. */
  semantics_version?: 1 | 2;
}

/**
 * Canonical, pagination-free API filter spec used by saved searches and POST
 * export. Presentation flags are deliberately excluded so both consumers
 * describe the candidate set itself, not the current table workspace.
 */
export function filtersToApiCriteria(
  filters: CandidateFilters,
): Record<string, unknown> {
  const params = filtersToApiParams(
    { ...filters, page: 1, savedSearchId: null },
    1,
  );
  const transient = new Set([
    "page",
    "page_size",
    "include_match_stats",
    "include_active_recruitments",
    "include_last_activity",
    "match_threshold",
  ]);
  return Object.fromEntries(
    Object.entries(params).filter(
      ([key, value]) => !transient.has(key) && value !== undefined,
    ),
  );
}

/**
 * Saved searches describe criteria, not the transient list workspace. This
 * keeps alerts stable and prevents reopening a saved search on an old page or
 * in a view the current user did not choose.
 */
export function encodeFilterCriteria(filters: CandidateFilters): URLSearchParams {
  return encodeFilters({
    ...filters,
    page: 1,
    view: "list",
    savedSearchId: null,
  });
}

/** Zaznaczenie na liście (`?sel=1,2,3`) — po powrocie z porównania (UAT B21). */
const SELECTED_IDS_PARAM = "sel";
const COMPARE_IDS_PARAM = "ids";

/**
 * Link do porównania niesie obok `ids` CAŁY kontekst listy (te same parametry
 * co `encodeFilters`), żeby „Wróć do kandydatów" mógł go oddać. Bez tego link
 * powrotny wskazywał gołe `/candidates`: wyszukiwanie znikało, a zaznaczenie
 * użyte do porównania trzeba było odtwarzać ręcznie.
 */
export function encodeCompareHref(filters: CandidateFilters, ids: number[]): string {
  const p = encodeFilters(filters);
  p.set(COMPARE_IDS_PARAM, ids.join(","));
  return `/candidates/compare?${p.toString()}`;
}

/**
 * Link powrotny z porównania: kontekst listy + `sel` = porównywane osoby.
 * Bez żadnych parametrów poza `ids` (stary link, wklejony ręcznie) → gołe
 * `/candidates`, ale z zaznaczeniem, jeśli `ids` są.
 */
export function decodeCompareBackHref(sp: URLSearchParams): string {
  const back = new URLSearchParams(sp);
  const ids = parseIdList(back.get(COMPARE_IDS_PARAM));
  back.delete(COMPARE_IDS_PARAM);
  back.delete(SELECTED_IDS_PARAM);
  if (ids.length) back.set(SELECTED_IDS_PARAM, ids.join(","));
  const qs = back.toString();
  return qs ? `/candidates?${qs}` : "/candidates";
}

/** Zaznaczenie odtwarzane przy wejściu na listę (`?sel=`); nieznane = puste. */
export function decodeSelectedIds(sp: URLSearchParams): number[] {
  return parseIdList(sp.get(SELECTED_IDS_PARAM));
}

function parseIdList(raw: string | null): number[] {
  if (!raw) return [];
  const seen = new Set<number>();
  for (const part of raw.split(",")) {
    const n = Number.parseInt(part, 10);
    if (Number.isFinite(n) && n > 0) seen.add(n);
  }
  return Array.from(seen);
}
