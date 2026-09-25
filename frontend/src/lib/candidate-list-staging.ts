/**
 * Lista kandydatów: filtry robocze kontra zastosowane (przycisk „Szukaj”,
 * 25.09.2026) i pamięć ostatniego wyszukiwania. Czyste funkcje — logikę
 * komponentu `CandidatesListV2` da się przez nie sprawdzić bez montowania.
 */

import {
  decodeFilters,
  encodeFilterCriteria,
  encodeFilters,
  type CandidateFilters,
} from "@/lib/url-filters";
import { locationSummary, rateSummary } from "@/lib/candidate-filter-groups";
import type { ListSearchMemory } from "@/lib/search-memory";

/** Kryteria bez tego, co działa od razu (strona, sortowanie, widok). */
function criteriaTokens(filters: CandidateFilters): string[] {
  const params = encodeFilterCriteria({ ...filters, sort: "newest", sortExplicit: false });
  const out: string[] = [];
  params.forEach((value, key) => {
    if (key === "q") {
      out.push(`q=${value.trim()}`);
      return;
    }
    for (const part of value.split(/[|,]/)) {
      if (part.trim()) out.push(`${key}=${part.trim()}`);
    }
  });
  return out;
}

/** Ile zmian czeka na „Szukaj” (każde słowo, filtr i wartość osobno). */
export function filterChangeCount(draft: CandidateFilters, applied: CandidateFilters): number {
  const a = criteriaTokens(applied);
  const d = criteriaTokens(draft);
  const remaining = new Map<string, number>();
  for (const token of a) remaining.set(token, (remaining.get(token) ?? 0) + 1);
  let changes = 0;
  for (const token of d) {
    const n = remaining.get(token) ?? 0;
    if (n > 0) remaining.set(token, n - 1);
    else changes += 1;
  }
  for (const n of remaining.values()) changes += n;
  return changes;
}

/** Czy te same kryteria (bez strony i sortowania). */
export function sameCriteria(a: CandidateFilters, b: CandidateFilters): boolean {
  return filterChangeCount(a, b) === 0;
}

/**
 * Stan zastosowany po zmianie szkicu, gdy nikt nie kliknął „Szukaj”:
 * sortowanie przechodzi od razu, strona tylko przy tych samych kryteriach,
 * reszta czeka.
 */
export function carryImmediate(
  applied: CandidateFilters,
  draft: CandidateFilters,
): CandidateFilters {
  if (encodeFilters(applied).toString() === encodeFilters(draft).toString()) return applied;
  if (sameCriteria(applied, draft)) return draft;
  if (applied.sort !== draft.sort || applied.sortExplicit !== draft.sortExplicit) {
    return { ...applied, sort: draft.sort, sortExplicit: draft.sortExplicit, page: 1 };
  }
  return applied;
}

/** Adres listy bez żadnego filtra, zapisanego wyszukiwania i zaznaczenia. */
export function isBareListQuery(params: URLSearchParams): boolean {
  if (params.has("ss") || params.has("sel")) return false;
  return encodeFilters(decodeFilters(params)).toString() === "";
}

/**
 * Parametry startowe listy: adres, a gdy jest goły — ostatnie wyszukiwanie
 * z tej karty (powrót z profilu, menu, innej strony).
 */
export function resolveInitialListParams(
  route: URLSearchParams,
  memory: ListSearchMemory | null,
): { params: URLSearchParams; restored: boolean } {
  if (!isBareListQuery(route) || !memory || !memory.query) {
    return { params: route, restored: false };
  }
  const params = new URLSearchParams(memory.query);
  for (const [key, value] of route.entries()) {
    if (!params.has(key)) params.set(key, value);
  }
  return { params, restored: true };
}

/** Słowa kluczowe wyszukiwania (do „ostatnio używanych” podpowiedzi). */
export function listSearchKeywords(filters: CandidateFilters): string[] {
  return [...filters.qAll, ...filters.qAny.flat(), ...filters.qNone].filter((w) => w.trim());
}

/** Krótki opis do menu „Ostatnie wyszukiwania”. */
export function listSearchLabel(filters: CandidateFilters): string {
  const parts: string[] = [];
  if (filters.q.trim()) parts.push(`„${filters.q.trim()}”`);
  if (filters.qAll.length) parts.push(filters.qAll.join(" + "));
  for (const group of filters.qAny) {
    if (group.length) parts.push(`(${group.join(" lub ")})`);
  }
  if (filters.qNone.length) parts.push(`bez ${filters.qNone.join(", ")}`);
  const rate = rateSummary(filters);
  if (rate) parts.push(rate);
  const location = locationSummary(filters);
  if (location) parts.push(location);
  const shown = new Set(["q", "q_all", "q_any", "q_none", "rate_min", "rate_max", "loc", "radius", "woj", "ls"]);
  const other = new Set<string>();
  encodeFilterCriteria({ ...filters, sort: "newest", sortExplicit: false }).forEach((_v, key) => {
    if (!shown.has(key)) other.add(key);
  });
  if (other.size) parts.push(`+${other.size} ${other.size === 1 ? "filtr" : other.size < 5 ? "filtry" : "filtrów"}`);
  return parts.length ? parts.join(" · ") : "Wszyscy kandydaci";
}
