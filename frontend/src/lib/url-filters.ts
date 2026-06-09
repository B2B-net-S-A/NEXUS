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

export type SortMode = "newest" | "oldest" | "name";
export type SkillCombine = "and" | "or";
export type RemoteMode = "remote" | "hybrid" | "onsite";
export type CandidatesView = "list" | "tiles";

export type CandidateStatusFilter = "active" | "passive" | "blacklisted";
export type EmploymentFilter = "at_client" | "available";
export type AvailabilityFilter =
  | "actively_looking"
  | "open_to_offers"
  | "not_looking"
  | "unknown";
export type PipelineStageFilter =
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
  sort: SortMode;
  page: number;
  remote: RemoteMode[];
  // Boolean skill expression typed into the "Umiejętności" box, e.g.
  // `Python AND React OR Vue -PHP`. Parsed into skill-scoped must/any/none
  // buckets at API time (see `filtersToApiParams` + `skill-expression.ts`).
  // Empty string = no skill filter. Round-trips in the URL as `skills_q`.
  skillsExpr: string;
  location: string;
  poolIds: number[];
  addedByIds: number[];
  currentCompany: string[];
  pastCompany: string[];
  currentTitle: string[];
  workedAtClientIds: number[];
  // Lata doświadczenia — inclusive numeric band (years of IT experience).
  // `null` on either side means that bound is open. The backend matches against
  // a derived per-candidate interval (exact `years_it_experience` or the coarse
  // Traffit bucket) using range-overlap, so a candidate counts when their
  // experience could fall inside [min, max].
  experienceMin: number | null;
  experienceMax: number | null;
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
  // "Aktualny etap" toggle. When true → force CURRENT-stage matching even with
  // who/when/client move-filters (sends `stage_current_only=true`). When false
  // (default) → omit the param so the backend auto-resolves: current for a bare
  // stage chip, historical as soon as a move-filter is present.
  stageCurrentOnly: boolean;
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
  sort: "newest",
  page: 1,
  remote: [],
  skillsExpr: "",
  location: "",
  poolIds: [],
  addedByIds: [],
  currentCompany: [],
  pastCompany: [],
  currentTitle: [],
  workedAtClientIds: [],
  experienceMin: null,
  experienceMax: null,
  stageMovedByIds: [],
  stageMovedAfter: "",
  stageMovedBefore: "",
  stageClientIds: [],
  stageCurrentOnly: false,
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
  if (f.sort !== "newest") p.set("sort", f.sort);
  if (f.page > 1) p.set("page", String(f.page));
  if (f.remote.length) p.set("remote", CSV(f.remote));
  if (f.skillsExpr.trim()) p.set("skills_q", f.skillsExpr.trim());
  if (f.location) p.set("loc", f.location);
  if (f.poolIds.length) p.set("pool", CSV(f.poolIds));
  if (f.addedByIds.length) p.set("added_by", CSV(f.addedByIds));
  if (f.currentCompany.length) p.set("cur_co", PIPE(f.currentCompany));
  if (f.pastCompany.length) p.set("past_co", PIPE(f.pastCompany));
  if (f.currentTitle.length) p.set("title", PIPE(f.currentTitle));
  if (f.workedAtClientIds.length) p.set("client_hist", CSV(f.workedAtClientIds));
  if (f.experienceMin !== null) p.set("exp_min", String(f.experienceMin));
  if (f.experienceMax !== null) p.set("exp_max", String(f.experienceMax));
  if (f.stageMovedByIds.length) p.set("stage_by", CSV(f.stageMovedByIds));
  if (f.stageMovedAfter) p.set("stage_from", f.stageMovedAfter);
  if (f.stageMovedBefore) p.set("stage_to", f.stageMovedBefore);
  if (f.stageClientIds.length) p.set("stage_client", CSV(f.stageClientIds));
  if (f.stageCurrentOnly) p.set("stage_current", "1");
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
    sortRaw === "oldest" || sortRaw === "name" ? sortRaw : "newest";
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
  return {
    q: sp.get("q") ?? "",
    status,
    employment,
    availability,
    pipelineStage,
    sort,
    page,
    remote,
    skillsExpr: decodeSkillsExpr(sp),
    location: sp.get("loc") ?? "",
    poolIds: parseCsvInt(sp.get("pool")),
    addedByIds: parseCsvInt(sp.get("added_by")),
    currentCompany: parsePipe(sp.get("cur_co")),
    pastCompany: parsePipe(sp.get("past_co")),
    currentTitle: parsePipe(sp.get("title")),
    workedAtClientIds: parseCsvInt(sp.get("client_hist")),
    experienceMin: parseYearBound(sp.get("exp_min")),
    experienceMax: parseYearBound(sp.get("exp_max")),
    stageMovedByIds: parseCsvInt(sp.get("stage_by")),
    stageMovedAfter: parseIsoDate(sp.get("stage_from")),
    stageMovedBefore: parseIsoDate(sp.get("stage_to")),
    stageClientIds: parseCsvInt(sp.get("stage_client")),
    stageCurrentOnly: sp.get("stage_current") === "1",
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
  // Parse the boolean skill expression into skill-scoped buckets. `must` →
  // `skills` (AND), `anyGroups` → repeated pipe-joined `skills_any`, `none` →
  // `skills_none`. `skill_combine` stays lowercase `"and"` — the backend's
  // multi-skill MUST default (uppercase would 422).
  const skillBuckets = parseSkillExpression(filters.skillsExpr);
  return {
    q: filters.q || undefined,
    status: filters.status.length ? filters.status : undefined,
    page,
    sort: filters.sort || undefined,
    skills: skillBuckets.must.length ? skillBuckets.must : undefined,
    skill_combine: skillBuckets.must.length > 1 ? "and" : undefined,
    skills_any: skillBuckets.anyGroups.length
      ? skillBuckets.anyGroups.map((g) => g.join("|"))
      : undefined,
    skills_none: skillBuckets.none.length ? skillBuckets.none : undefined,
    remote_policy: filters.remote.length ? filters.remote : undefined,
    employment: filters.employment.length ? filters.employment : undefined,
    availability: filters.availability.length ? filters.availability : undefined,
    pipeline_stage: filters.pipelineStage.length ? filters.pipelineStage : undefined,
    location: filters.location || undefined,
    talent_pool_id: filters.poolIds.length ? filters.poolIds : undefined,
    added_by_user_id: filters.addedByIds.length ? filters.addedByIds : undefined,
    current_company: filters.currentCompany.length ? filters.currentCompany : undefined,
    past_company: filters.pastCompany.length ? filters.pastCompany : undefined,
    current_title: filters.currentTitle.length ? filters.currentTitle : undefined,
    worked_at_client_id: filters.workedAtClientIds.length
      ? filters.workedAtClientIds
      : undefined,
    min_experience: filters.experienceMin ?? undefined,
    max_experience: filters.experienceMax ?? undefined,
    stage_moved_by: filters.stageMovedByIds.length
      ? filters.stageMovedByIds
      : undefined,
    stage_moved_after: filters.stageMovedAfter || undefined,
    stage_moved_before: filters.stageMovedBefore || undefined,
    stage_client_id: filters.stageClientIds.length
      ? filters.stageClientIds
      : undefined,
    // Only send when forcing current-stage matching; omitting lets the backend
    // auto-resolve (current for a bare stage, historical with a move-filter).
    stage_current_only: filters.stageCurrentOnly ? true : undefined,
    q_all: filters.qAll.length ? filters.qAll : undefined,
    // ANY OR-groups → one repeated `q_any_group` value per group (pipe-joined).
    q_any_group: filters.qAny.some((g) => g.length)
      ? filters.qAny.filter((g) => g.length).map((g) => g.join("|"))
      : undefined,
    q_none: filters.qNone.length ? filters.qNone : undefined,
    ...extras,
  };
}
