/**
 * Candidate search URL filter state — single source of truth.
 *
 * Every filter in `CandidatesListV2` round-trips through `encodeFilters` /
 * `decodeFilters`. Saved searches store the encoded querystring, so adding
 * new fields to `CandidateFilters` is backward-compatible — `decodeFilters`
 * ignores unknown params and fills unknown fields with defaults.
 */

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

export interface CandidateFilters {
  q: string;
  status: CandidateStatusFilter[];
  employment: EmploymentFilter[];
  availability: AvailabilityFilter[];
  sort: SortMode;
  page: number;
  remote: RemoteMode[];
  skills: string[];
  skillCombine: SkillCombine;
  location: string;
  poolIds: number[];
  addedByIds: number[];
  currentCompany: string[];
  pastCompany: string[];
  currentTitle: string[];
  workedAtClientIds: number[];
  view: CandidatesView;
  savedSearchId: number | null;
  // Traffit-style advanced search buckets. Each phrase matches ILIKE
  // across name/email/CV/ai_summary/competence_category/experience/skills/tags.
  qAll: string[]; // every phrase must match (AND)
  qAny: string[]; // at least one phrase matches (OR)
  qNone: string[]; // none of these phrases may match (NOT)
}

export const DEFAULT_FILTERS: CandidateFilters = {
  q: "",
  status: [],
  employment: [],
  availability: [],
  sort: "newest",
  page: 1,
  remote: [],
  skills: [],
  skillCombine: "and",
  location: "",
  poolIds: [],
  addedByIds: [],
  currentCompany: [],
  pastCompany: [],
  currentTitle: [],
  workedAtClientIds: [],
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

// Pipe-separated list — used for company/title values that may contain commas
// (e.g. "Intel, Inc."). Safer than comma for free-text inputs.
const PIPE = (xs: string[]): string => xs.join("|");
const parsePipe = (raw: string | null): string[] =>
  raw ? raw.split("|").map((x) => x.trim()).filter(Boolean) : [];

export function encodeFilters(f: CandidateFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  if (f.status.length) p.set("status", CSV(f.status));
  if (f.employment.length) p.set("employment", CSV(f.employment));
  if (f.availability.length) p.set("availability", CSV(f.availability));
  if (f.sort !== "newest") p.set("sort", f.sort);
  if (f.page > 1) p.set("page", String(f.page));
  if (f.remote.length) p.set("remote", CSV(f.remote));
  if (f.skills.length) p.set("skills", CSV(f.skills));
  if (f.skills.length > 1 && f.skillCombine !== "and") p.set("skill_combine", f.skillCombine);
  if (f.location) p.set("loc", f.location);
  if (f.poolIds.length) p.set("pool", CSV(f.poolIds));
  if (f.addedByIds.length) p.set("added_by", CSV(f.addedByIds));
  if (f.currentCompany.length) p.set("cur_co", PIPE(f.currentCompany));
  if (f.pastCompany.length) p.set("past_co", PIPE(f.pastCompany));
  if (f.currentTitle.length) p.set("title", PIPE(f.currentTitle));
  if (f.workedAtClientIds.length) p.set("client_hist", CSV(f.workedAtClientIds));
  if (f.qAll.length) p.set("q_all", PIPE(f.qAll));
  if (f.qAny.length) p.set("q_any", PIPE(f.qAny));
  if (f.qNone.length) p.set("q_none", PIPE(f.qNone));
  if (f.view !== "list") p.set("view", f.view);
  if (f.savedSearchId !== null) p.set("ss", String(f.savedSearchId));
  return p;
}

export function decodeFilters(sp: URLSearchParams): CandidateFilters {
  const sortRaw = sp.get("sort");
  const sort: SortMode =
    sortRaw === "oldest" || sortRaw === "name" ? sortRaw : "newest";
  const skillCombineRaw = sp.get("skill_combine");
  const skillCombine: SkillCombine = skillCombineRaw === "or" ? "or" : "and";
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
    sort,
    page,
    remote,
    skills: parseCsv(sp.get("skills")),
    skillCombine,
    location: sp.get("loc") ?? "",
    poolIds: parseCsvInt(sp.get("pool")),
    addedByIds: parseCsvInt(sp.get("added_by")),
    currentCompany: parsePipe(sp.get("cur_co")),
    pastCompany: parsePipe(sp.get("past_co")),
    currentTitle: parsePipe(sp.get("title")),
    workedAtClientIds: parseCsvInt(sp.get("client_hist")),
    view,
    savedSearchId,
    qAll: parsePipe(sp.get("q_all")),
    qAny: parsePipe(sp.get("q_any")),
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
  return {
    q: filters.q || undefined,
    status: filters.status.length ? filters.status : undefined,
    page,
    sort: filters.sort || undefined,
    skills: filters.skills.length ? filters.skills : undefined,
    skill_combine:
      filters.skills.length > 1 ? filters.skillCombine.toUpperCase() : undefined,
    remote_policy: filters.remote.length ? filters.remote : undefined,
    employment: filters.employment.length ? filters.employment : undefined,
    availability: filters.availability.length ? filters.availability : undefined,
    location: filters.location || undefined,
    talent_pool_id: filters.poolIds.length ? filters.poolIds : undefined,
    added_by_user_id: filters.addedByIds.length ? filters.addedByIds : undefined,
    current_company: filters.currentCompany.length ? filters.currentCompany : undefined,
    past_company: filters.pastCompany.length ? filters.pastCompany : undefined,
    current_title: filters.currentTitle.length ? filters.currentTitle : undefined,
    worked_at_client_id: filters.workedAtClientIds.length
      ? filters.workedAtClientIds
      : undefined,
    q_all: filters.qAll.length ? filters.qAll : undefined,
    q_any: filters.qAny.length ? filters.qAny : undefined,
    q_none: filters.qNone.length ? filters.qNone : undefined,
    ...extras,
  };
}
