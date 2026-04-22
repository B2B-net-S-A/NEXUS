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

export interface CandidateFilters {
  q: string;
  status: string;
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
}

export const DEFAULT_FILTERS: CandidateFilters = {
  q: "",
  status: "",
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
  if (f.status) p.set("status", f.status);
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
  const pageRaw = Number.parseInt(sp.get("page") ?? "1", 10);
  const page = Number.isFinite(pageRaw) && pageRaw > 0 ? pageRaw : 1;
  const ssRaw = sp.get("ss");
  const ssNum = ssRaw !== null ? Number.parseInt(ssRaw, 10) : NaN;
  const savedSearchId = Number.isFinite(ssNum) && ssNum > 0 ? ssNum : null;
  return {
    q: sp.get("q") ?? "",
    status: sp.get("status") ?? "",
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
  };
}

export function filtersEqual(a: CandidateFilters, b: CandidateFilters): boolean {
  return encodeFilters(a).toString() === encodeFilters(b).toString();
}
