/**
 * Jeden format zapisanego wyszukiwania kandydatów (`version: 3`) — lustro
 * `backend/app/services/saved_search_payload.py`.
 *
 * Pod `entity="candidates"` żyły dwa niezgodne ładunki: lista
 * (`{version: 2, qs, api}`, `candidate-saved-search.ts`) i surowe żądanie
 * wyszukiwarki (`candidate-search-request.ts`). Format v3 niesie JEDNO żądanie
 * we wspólnym kształcie i deklaruje `semantics_version: 2`, czyli semantykę
 * filtrów wspólną dla `GET /api/candidates` i `POST /api/search/candidates`.
 *
 * Parytet z backendem pilnuje `__fixtures__/saved-search-unified-cases.json`
 * (czyta go vitest i pytest). Zmiana mapowania = ten plik + oba adaptery.
 */

export const UNIFIED_VERSION = 3;
export const UNIFIED_SEMANTICS = 2;

export type SavedSearchOrigin = "candidates_list" | "search_request";
export type UnifiedSavedSearchFormat =
  | "unified"
  | "candidates_list"
  | "search_request"
  | "unknown";

type Dict = Record<string, unknown>;

/** Żądanie we wspólnym kształcie (pola puste są pomijane). */
export interface UnifiedCandidateSearchRequest {
  semantics_version: 2;
  q?: string;
  text_mode?: "auto" | "literal" | "semantic";
  q_all?: string[];
  q_any_groups?: string[][];
  q_none?: string[];
  skills_required?: string[];
  skills_required_any_groups?: string[][];
  skills_preferred?: string[];
  skills_excluded?: string[];
  status?: string[];
  availability_status?: string[];
  open_to?: string[];
  competence_category_ids?: number[];
  rate_hourly_min?: number;
  rate_hourly_max?: number;
  experience_years_min?: number;
  experience_years_max?: number;
  tags?: string[];
  location_cities?: string[];
  location_countries?: string[];
  /** `location_only` = dotychczasowy zakres listy (sama kolumna `location`). */
  location_scope?: "city_or_location" | "location_only";
  hide_unknown?: boolean;
  /**
   * Języki (każdy wymagany) — `{code: "EN", min_level?: "B2"}`. Od 22.09.2026
   * wspólne: lista przyjmuje je jako `languages=kod[:POZIOM]`.
   */
  languages?: Array<{ code: string; min_level?: string }>;
  /** Filtry, które zna tylko lista (pule, etapy, zatrudnienie…). */
  list_only?: Dict;
  /** Filtry, które zna tylko wyszukiwarka (języki, źródła, tryb…). */
  search_only?: Dict;
}

export interface UnifiedSavedSearchPayload {
  version: 3;
  semantics_version: 2;
  origin: SavedSearchOrigin;
  request: UnifiedCandidateSearchRequest;
  qs?: string;
  legacy?: unknown;
  migration?: Dict;
}

const SEARCH_REQUEST_KEYS = [
  "q",
  "q_all",
  "q_any",
  "q_any_groups",
  "q_none",
  "skills_must",
  "skills_any",
  "skills_none",
  "competence_category_ids",
  "location_cities",
  "location_countries",
  "languages",
  "rate_hourly_min",
  "rate_hourly_max",
  "status",
  "availability_status",
  "search_mode",
  "sort",
  "exclude_blacklisted",
] as const;

const LIST_DROPPED = new Set([
  "page",
  "page_size",
  "id_after",
  "updated_after",
  "include_match_stats",
  "include_active_recruitments",
  "include_last_activity",
  "match_threshold",
  "profile_id",
  "semantics_version",
  "skill_combine",
]);
const SEARCH_DROPPED = new Set(["page", "page_size", "semantics_version"]);

const SHARED_KEYS = [
  "q",
  "text_mode",
  "q_all",
  "q_any_groups",
  "q_none",
  "skills_required",
  "skills_required_any_groups",
  "skills_preferred",
  "skills_excluded",
  "status",
  "availability_status",
  "open_to",
  "competence_category_ids",
  "rate_hourly_min",
  "rate_hourly_max",
  "experience_years_min",
  "experience_years_max",
  "tags",
  "location_cities",
  "location_countries",
  "location_scope",
  "hide_unknown",
  "languages",
] as const;

const OPEN_TO_FLAGS: ReadonlyArray<readonly [string, string]> = [
  ["open_to_side_projects", "side_projects"],
  ["open_to_sales_support", "sales_support"],
  ["open_to_expert_consult", "expert_consult"],
];

/** Lustro `_languages_from_list`: `"en:b2"` → `{code: "EN", min_level: "B2"}`. */
function languagesFromList(value: unknown): Dict[] {
  const out: Dict[] = [];
  for (const entry of asList(value)) {
    if (isDict(entry)) {
      out.push({ ...entry });
      continue;
    }
    const raw = String(entry).trim();
    const idx = raw.indexOf(":");
    const code = (idx >= 0 ? raw.slice(0, idx) : raw).trim();
    if (!code) continue;
    const item: Dict = { code: code.toUpperCase() };
    const level = idx >= 0 ? raw.slice(idx + 1).trim() : "";
    if (idx >= 0 && level) {
      item.min_level = level.toLowerCase() === "native" ? "native" : level.toUpperCase();
    }
    out.push(item);
  }
  return out;
}

/** Lustro `_languages_to_list`: `{code, min_level?}` → `kod[:POZIOM]`. */
function languagesToList(value: unknown): string[] {
  const out: string[] = [];
  for (const entry of asList(value)) {
    if (isDict(entry)) {
      const code = String(entry.code ?? "").trim();
      if (!code) continue;
      const level = entry.min_level;
      out.push(level ? `${code}:${String(level)}` : code);
    } else if (String(entry).trim()) {
      out.push(String(entry).trim());
    }
  }
  return out;
}

const isDict = (v: unknown): v is Dict =>
  !!v && typeof v === "object" && !Array.isArray(v);

const isEmpty = (v: unknown): boolean =>
  v === null ||
  v === undefined ||
  v === "" ||
  (Array.isArray(v) && v.length === 0) ||
  (isDict(v) && Object.keys(v).length === 0);

const asList = (v: unknown): unknown[] =>
  isEmpty(v) ? [] : Array.isArray(v) ? [...v] : [v];

const splitPipe = (v: unknown): string[] =>
  String(v ?? "")
    .split("|")
    .map((part) => part.trim())
    .filter(Boolean);

function compact(request: Dict): UnifiedCandidateSearchRequest {
  const out: Dict = { semantics_version: UNIFIED_SEMANTICS };
  for (const key of SHARED_KEYS) {
    if (!isEmpty(request[key])) out[key] = request[key];
  }
  for (const key of ["list_only", "search_only"] as const) {
    const source = request[key];
    if (!isDict(source)) continue;
    const extra: Dict = {};
    for (const [k, v] of Object.entries(source)) {
      if (!isEmpty(v)) extra[k] = v;
    }
    if (Object.keys(extra).length) out[key] = extra;
  }
  return out as unknown as UnifiedCandidateSearchRequest;
}

export function detectUnifiedFormat(filters: unknown): UnifiedSavedSearchFormat {
  if (!isDict(filters)) return "unknown";
  if (filters.version === UNIFIED_VERSION && isDict(filters.request)) {
    return "unified";
  }
  if (typeof filters.qs === "string" || isDict(filters.api)) {
    return "candidates_list";
  }
  if (SEARCH_REQUEST_KEYS.some((k) => k in filters)) return "search_request";
  return "unknown";
}

/** Parametry `GET /api/candidates` (`filters.api`) → żądanie wspólne. */
export function listApiToUnified(api: Dict): UnifiedCandidateSearchRequest {
  const required = asList(api.skills_required).map(String);
  const groups = asList(api.skills_required_any_groups).map(splitPipe);
  const legacySkills = asList(api.skills)
    .map(String)
    .filter((s) => s.trim());
  if (legacySkills.length) {
    const combine = String(api.skill_combine ?? "and")
      .trim()
      .toLowerCase();
    if (combine === "or") groups.push(legacySkills.flatMap(splitPipe));
    else required.push(...legacySkills);
  }
  groups.push(...asList(api.skills_any).map(splitPipe));
  const excluded = [
    ...asList(api.skills_none),
    ...asList(api.skills_excluded),
  ].flatMap(splitPipe);

  const qGroups: string[][] = [];
  if (asList(api.q_any).length) qGroups.push(asList(api.q_any).map(String));
  qGroups.push(...asList(api.q_any_group).map(splitPipe));

  const consumed = new Set([
    "q",
    "text_mode",
    "q_all",
    "q_any",
    "q_any_group",
    "q_none",
    "skills",
    "skills_any",
    "skills_none",
    "skills_required",
    "skills_required_any_groups",
    "skills_preferred",
    "skills_excluded",
    "status",
    "availability",
    "open_to",
    "competence_category_id",
    "min_rate",
    "max_rate",
    "min_experience",
    "max_experience",
    "tags",
    "location",
    "location_cities",
    "country",
    "location_scope",
    "hide_unknown",
    "languages",
  ]);
  const listOnly: Dict = {};
  for (const [k, v] of Object.entries(api)) {
    if (!consumed.has(k) && !LIST_DROPPED.has(k)) listOnly[k] = v;
  }

  return compact({
    q: api.q,
    text_mode: api.text_mode,
    q_all: asList(api.q_all),
    q_any_groups: qGroups.filter((g) => g.length),
    q_none: asList(api.q_none),
    skills_required: required,
    skills_required_any_groups: groups.filter((g) => g.length),
    skills_preferred: asList(api.skills_preferred),
    skills_excluded: excluded,
    status: asList(api.status),
    availability_status: asList(api.availability),
    open_to: asList(api.open_to),
    competence_category_ids: asList(api.competence_category_id),
    rate_hourly_min: api.min_rate,
    rate_hourly_max: api.max_rate,
    experience_years_min: api.min_experience,
    experience_years_max: api.max_experience,
    tags: asList(api.tags),
    location_cities: [...asList(api.location), ...asList(api.location_cities)],
    location_countries: asList(api.country),
    location_scope: api.location_scope,
    hide_unknown: api.hide_unknown,
    languages: languagesFromList(api.languages),
    list_only: listOnly,
  });
}

/** Surowe `CandidateSearchRequest` → żądanie wspólne. */
export function searchRequestToUnified(body: Dict): UnifiedCandidateSearchRequest {
  const preferred = [
    ...asList(body.skills_must),
    ...asList(body.skills_any),
    ...asList(body.skills_preferred),
  ];
  const excluded = [
    ...asList(body.skills_none),
    ...asList(body.skills_excluded),
  ].flatMap(splitPipe);
  const groups = asList(body.skills_required_any_groups).map((group) =>
    asList(group).flatMap(splitPipe),
  );
  const qGroups: string[][] = [];
  if (asList(body.q_any).length) qGroups.push(asList(body.q_any).map(String));
  for (const group of asList(body.q_any_groups)) {
    const parts = asList(group).flatMap(splitPipe);
    if (parts.length) qGroups.push(parts);
  }

  const openTo = asList(body.open_to).map(String);
  const searchOnly: Dict = {};
  for (const [flag, name] of OPEN_TO_FLAGS) {
    if (body[flag] === true && !openTo.includes(name)) openTo.push(name);
    else if (body[flag] === false) searchOnly[flag] = false;
  }

  const consumed = new Set<string>([
    "q",
    "text_mode",
    "q_all",
    "q_any",
    "q_any_groups",
    "q_none",
    "skills_must",
    "skills_any",
    "skills_none",
    "skills_required",
    "skills_required_any_groups",
    "skills_preferred",
    "skills_excluded",
    "status",
    "availability_status",
    "open_to",
    "competence_category_ids",
    "rate_hourly_min",
    "rate_hourly_max",
    "experience_years_min",
    "experience_years_max",
    "tags",
    "location_cities",
    "location_countries",
    "location_scope",
    "hide_unknown",
    "languages",
    ...OPEN_TO_FLAGS.map(([flag]) => flag),
  ]);
  for (const [k, v] of Object.entries(body)) {
    if (!consumed.has(k) && !SEARCH_DROPPED.has(k)) searchOnly[k] = v;
  }

  return compact({
    q: body.q,
    text_mode: body.text_mode,
    q_all: asList(body.q_all),
    q_any_groups: qGroups,
    q_none: asList(body.q_none),
    skills_required: asList(body.skills_required),
    skills_required_any_groups: groups.filter((g) => g.length),
    skills_preferred: preferred,
    skills_excluded: excluded,
    status: asList(body.status),
    availability_status: asList(body.availability_status),
    open_to: openTo,
    competence_category_ids: asList(body.competence_category_ids),
    rate_hourly_min: body.rate_hourly_min,
    rate_hourly_max: body.rate_hourly_max,
    experience_years_min: body.experience_years_min,
    experience_years_max: body.experience_years_max,
    tags: asList(body.tags),
    languages: asList(body.languages),
    location_cities: asList(body.location_cities),
    location_countries: asList(body.location_countries),
    location_scope: body.location_scope,
    hide_unknown: body.hide_unknown,
    search_only: searchOnly,
  });
}

export interface ReadSavedSearchResult {
  format: UnifiedSavedSearchFormat;
  origin: SavedSearchOrigin | null;
  /** `null`, gdy zapisu nie da się odczytać (np. najstarsze `{qs}` bez `api`). */
  request: UnifiedCandidateSearchRequest | null;
}

/** Dowolny z trzech formatów → żądanie wspólne. */
export function readSavedSearch(filters: unknown): ReadSavedSearchResult {
  const format = detectUnifiedFormat(filters);
  if (format === "unified") {
    const f = filters as Dict;
    const origin: SavedSearchOrigin =
      f.origin === "search_request" ? "search_request" : "candidates_list";
    return { format, origin, request: compact(f.request as Dict) };
  }
  if (format === "candidates_list") {
    const api = (filters as Dict).api;
    return {
      format,
      origin: "candidates_list",
      request: isDict(api) ? listApiToUnified(api) : null,
    };
  }
  if (format === "search_request") {
    return {
      format,
      origin: "search_request",
      request: searchRequestToUnified(filters as Dict),
    };
  }
  return { format, origin: null, request: null };
}

const LIST_DIRECT: ReadonlyArray<readonly [string, string]> = [
  ["q", "q"],
  ["text_mode", "text_mode"],
  ["q_all", "q_all"],
  ["q_none", "q_none"],
  ["skills_required", "skills_required"],
  ["skills_preferred", "skills_preferred"],
  ["skills_excluded", "skills_excluded"],
  ["status", "status"],
  ["availability_status", "availability"],
  ["open_to", "open_to"],
  ["competence_category_ids", "competence_category_id"],
  ["rate_hourly_min", "min_rate"],
  ["rate_hourly_max", "max_rate"],
  ["experience_years_min", "min_experience"],
  ["experience_years_max", "max_experience"],
  ["tags", "tags"],
  ["location_cities", "location_cities"],
  ["location_countries", "country"],
  ["location_scope", "location_scope"],
  ["hide_unknown", "hide_unknown"],
];

/** Żądanie wspólne → parametry `GET /api/candidates` (zawsze v2). */
export function unifiedToListParams(request: UnifiedCandidateSearchRequest): Dict {
  const req = compact(request as unknown as Dict) as unknown as Dict;
  const out: Dict = { ...((req.list_only as Dict | undefined) ?? {}) };
  out.semantics_version = UNIFIED_SEMANTICS;
  for (const [source, target] of LIST_DIRECT) {
    if (source in req) out[target] = req[source];
  }
  if ("skills_required_any_groups" in req) {
    out.skills_required_any_groups = (
      req.skills_required_any_groups as string[][]
    ).map((g) => g.join("|"));
  }
  if ("q_any_groups" in req) {
    out.q_any_group = (req.q_any_groups as string[][]).map((g) => g.join("|"));
  }
  if ("languages" in req) out.languages = languagesToList(req.languages);
  return out;
}

/** Żądanie wspólne → ciało `POST /api/search/candidates` (zawsze v2). */
export function unifiedToSearchBody(request: UnifiedCandidateSearchRequest): Dict {
  const req = compact(request as unknown as Dict) as unknown as Dict;
  const out: Dict = { ...((req.search_only as Dict | undefined) ?? {}) };
  out.semantics_version = UNIFIED_SEMANTICS;
  for (const key of SHARED_KEYS) {
    if (key in req) out[key] = req[key];
  }
  return out;
}

const GAP_IGNORED = new Set(["sort", "search_mode"]);

/**
 * Pola, których lista nie umie wyrazić (języki, źródła…). Lustro
 * `list_engine_gaps`: `exclude_blacklisted` i `exclude_in_job_id` zawężają
 * wynik, więc są luką, chyba że nic nie zawężają (runda 8, R8-N10-6).
 */
export function listEngineGaps(request: UnifiedCandidateSearchRequest): string[] {
  const searchOnly = (request.search_only ?? {}) as Record<string, unknown>;
  const statuses = request.status ?? [];
  return Object.keys(searchOnly)
    .filter((k) => {
      if (GAP_IGNORED.has(k)) return false;
      const value = searchOnly[k];
      if (k === "exclude_blacklisted") {
        return Boolean(value) && !(statuses.length > 0 && !statuses.includes("blacklisted"));
      }
      if (k === "exclude_in_job_id") return value !== null && value !== undefined;
      return true;
    })
    .sort();
}

/**
 * Flagi żądania zmieniające wynik (`hide_unknown`, `location_scope`) także
 * w querystringu UI listy (`hu=1`, `ls=location_only`) — lustro
 * `with_request_flags` (CAND-06). Dopisuje tylko brakujące.
 */
export function withRequestFlags(
  qs: string,
  request: UnifiedCandidateSearchRequest,
): string {
  const parts = qs.split("&").filter(Boolean);
  const keys = new Set(parts.map((p) => p.split("=", 1)[0]));
  const req = request as unknown as Dict;
  if (req.hide_unknown === true && !keys.has("hu")) parts.push("hu=1");
  if (req.location_scope === "location_only" && !keys.has("ls")) {
    parts.push("ls=location_only");
  }
  return parts.join("&");
}

/** Dopisuje `sv=2` do querystringu listy (raz). */
export function withSemanticsMarker(qs: string): string {
  const parts = qs.split("&").filter((p) => p && !p.startsWith("sv="));
  parts.push(`sv=${UNIFIED_SEMANTICS}`);
  return parts.join("&");
}

/** Zapis v3; oryginał zostaje w `legacy`. */
export function buildUnifiedPayload(
  filters: Dict,
  origin: SavedSearchOrigin,
  request: UnifiedCandidateSearchRequest,
  migration?: Dict,
): UnifiedSavedSearchPayload {
  const payload: Dict = {
    version: UNIFIED_VERSION,
    semantics_version: UNIFIED_SEMANTICS,
    origin,
    request: compact(request as unknown as Dict),
  };
  if (origin === "candidates_list" && typeof filters.qs === "string") {
    payload.qs = withSemanticsMarker(withRequestFlags(filters.qs, request));
  }
  payload.legacy =
    detectUnifiedFormat(filters) === "unified" ? filters.legacy : filters;
  if (migration !== undefined) payload.migration = migration;
  return payload as unknown as UnifiedSavedSearchPayload;
}

/**
 * Zapis (dowolny format) → stan widoku `CandidateSearchView`.
 *
 * Widok ma jawne kubełki umiejętności i „Otwarty na" (semantyka v2), więc
 * zapis v3 wraca jako ciało wyszukiwarki bez przekładania na pola legacy.
 * Surowe żądanie legacy wraca bez zmian — widok przepuszcza je przez
 * `toSearchSemanticsV2` (`candidate-search-semantics.ts`), które korzysta
 * z `searchRequestToUnified` wyżej, więc mapowanie legacy jest jedno.
 */
export function savedSearchToSearchViewRequest(filters: unknown): Dict | null {
  const format = detectUnifiedFormat(filters);
  if (format === "search_request") return { ...(filters as Dict) };
  if (format !== "unified") return null;
  const { request } = readSavedSearch(filters);
  if (!request) return null;
  return unifiedToSearchBody(request);
}
