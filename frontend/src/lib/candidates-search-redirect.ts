/**
 * Stary adres wyszukiwarki (`/candidates?mode=search&s=…`, także
 * `/candidates/search`) → adres jednej listy kandydatów (22.09.2026).
 *
 * Od uproszczenia ekranu „Kandydaci" wyszukiwanie tekstem, filtry i
 * sortowanie żyją na liście. Zapisane zakładki i linki z powiadomień niosą
 * jednak stan wyszukiwarki w `?s=` (JSON żądania). Przekładamy go przez ten
 * sam adapter co migracja zapisanych wyszukiwań (`searchRequestToUnified`),
 * żeby lista pokazała to samo wyszukiwanie — nie kopię reguł mapowania.
 *
 * Czego lista nie wyraża (tagi, kraje, źródła, „ma CV"…), zostaje pominięte:
 * lista z tymi filtrami pokazałaby SZERSZY zbiór, ale to wciąż uczciwszy
 * punkt startu niż pusty ekran. Kontekst rekrutacji (`job`) nie jest tu
 * obsługiwany — taki adres dalej otwiera wyszukiwarkę rekrutacji.
 */

import type { CandidateSearchRequest } from "@/lib/candidate-search-api";
import {
  decodeSearchRequest,
  SEARCH_REQUEST_URL_PARAM,
} from "@/lib/candidate-search-request";
import { unifiedLanguageToFilter } from "@/lib/candidate-languages";
import { searchRequestToUnified } from "@/lib/saved-search-unified";
import { serializeSkillBuckets } from "@/lib/skill-expression";
import {
  DEFAULT_FILTERS,
  encodeFilters,
  type AvailabilityFilter,
  type CandidateFilters,
  type CandidateStatusFilter,
} from "@/lib/url-filters";
import type { OpenToValue } from "@/lib/filter-options";

/** Kształt bazowy dla dekodera `?s=` — listy muszą być listami. */
const SEARCH_BASE: CandidateSearchRequest = {
  q: null,
  q_all: [],
  q_any: [],
  q_any_groups: [],
  q_none: [],
  competence_category_ids: [],
  skills_must: [],
  skills_any: [],
  skills_none: [],
  skills_required: [],
  skills_required_any_groups: [],
  skills_preferred: [],
  skills_excluded: [],
  open_to: [],
  languages: [],
  location_cities: [],
  location_countries: [],
  status: [],
  availability_status: [],
  sources: [],
  tags: [],
  sort: "relevance",
  page: 1,
  page_size: 50,
  search_mode: "hybrid",
  semantics_version: 2,
  text_mode: null,
  hide_unknown: null,
};

const STATUS: ReadonlySet<string> = new Set(["active", "passive", "blacklisted"]);
const AVAILABILITY: ReadonlySet<string> = new Set([
  "actively_looking",
  "open_to_offers",
  "not_looking",
  "unknown",
]);
const OPEN_TO: ReadonlySet<string> = new Set([
  "side_projects",
  "sales_support",
  "expert_consult",
]);

const strings = (v: unknown): string[] =>
  Array.isArray(v) ? v.map((x) => String(x).trim()).filter(Boolean) : [];
const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) && v >= 0 ? Math.floor(v) : null;

/** Żądanie wyszukiwarki (dowolnie stare) → filtry listy. */
export function searchRequestToListFilters(
  request: CandidateSearchRequest,
): CandidateFilters {
  const u = searchRequestToUnified(request as unknown as Record<string, unknown>);
  const must: string[] = [];
  const anyGroups: string[][] = [];
  for (const entry of u.skills_required ?? []) {
    const parts = entry.split("|").map((p) => p.trim()).filter(Boolean);
    if (parts.length > 1) anyGroups.push(parts);
    else if (parts.length === 1) must.push(parts[0]);
  }
  for (const group of u.skills_required_any_groups ?? []) {
    if (group.length) anyGroups.push(group);
  }
  const textMode = u.text_mode === "literal" || u.text_mode === "semantic" ? u.text_mode : "auto";
  const q = (u.q ?? "").trim();
  return {
    ...DEFAULT_FILTERS,
    q,
    textMode,
    skillsExpr: serializeSkillBuckets({ must, anyGroups, none: u.skills_excluded ?? [] }),
    skillsPreferred: u.skills_preferred ?? [],
    status: strings(u.status).filter((s): s is CandidateStatusFilter => STATUS.has(s)),
    availability: strings(u.availability_status).filter(
      (s): s is AvailabilityFilter => AVAILABILITY.has(s),
    ),
    openTo: strings(u.open_to).filter((s): s is OpenToValue => OPEN_TO.has(s)),
    competenceCategoryIds: (u.competence_category_ids ?? []).filter(
      (n): n is number => Number.isInteger(n),
    ),
    rateMin: num(u.rate_hourly_min),
    rateMax: num(u.rate_hourly_max),
    experienceMin: num(u.experience_years_min),
    experienceMax: num(u.experience_years_max),
    location: strings(u.location_cities)[0] ?? "",
    hideUnknown: u.hide_unknown === true,
    languages: (u.languages ?? [])
      .map(unifiedLanguageToFilter)
      .filter((v): v is string => v !== null),
    qAll: strings(u.q_all),
    qAny: (u.q_any_groups ?? []).map(strings).filter((g) => g.length > 0),
    qNone: strings(u.q_none),
    // Wyszukiwarka domyślnie szereguje po trafności — na liście to i tak
    // domyślne zachowanie przy wpisanym tekście, więc nie utrwalamy wyboru.
    sort: "newest",
  };
}

/** Adres listy dla starego stanu wyszukiwarki (`s` z adresu). */
export function searchStateToListHref(params: URLSearchParams): string {
  const request = decodeSearchRequest(params.get(SEARCH_REQUEST_URL_PARAM), SEARCH_BASE);
  const qs = encodeFilters(searchRequestToListFilters(request)).toString();
  return qs ? `/candidates?${qs}` : "/candidates";
}
