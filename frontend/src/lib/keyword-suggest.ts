/**
 * Podpowiedzi do pól słów kluczowych (`GET /api/candidates/keywords/suggest`).
 *
 * Kolejność źródeł w liście: kontekst (np. must-have Championa rekrutacji) →
 * ostatnio używane słowa → słownik z bazy → wzorzec „jav*” → „dokładnie jak
 * wpisane”. Pozycje dedupowane po nazwie bez polskich znaków; słowa, które
 * już są w polu, nie wracają jako podpowiedź.
 */

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";

export const KEYWORD_SUGGEST_ENDPOINT = "/api/candidates/keywords/suggest";

export type KeywordSuggestKind = "skill" | "title" | "prefix";

export interface KeywordSuggestion {
  label: string;
  kind: KeywordSuggestKind;
  insert: string;
  alias?: string | null;
  category?: string | null;
  count?: number | null;
  /** Inne zapisy tej umiejętności ze słownika (przycisk „+ z wariantami”). */
  variants?: string[] | null;
}

export interface KeywordSuggestResponse {
  items: KeywordSuggestion[];
  wildcard: KeywordSuggestion | null;
}

export type SuggestionGroup = "context" | "recent" | "base" | "pattern";

export interface SuggestionOption {
  key: string;
  insert: string;
  /** Część etykiety pogrubiona (wpisany początek), reszta zwykła. */
  hit: string;
  rest: string;
  note: string;
  kindLabel: string;
  count: number | null;
  group: SuggestionGroup;
  /** Warianty dodawane razem z `insert` (pozycja „+ z wariantami”). */
  variants?: string[];
}

export const GROUP_LABEL: Record<SuggestionGroup, string> = {
  context: "Z tej rekrutacji",
  recent: "Ostatnio używane",
  base: "Z bazy",
  pattern: "Wzorzec",
};

export interface KeywordContextItem {
  label: string;
  /** Np. „must-have”, „nice-to-have”. */
  note?: string;
}

/** Małe litery, bez polskich znaków (lustro `keyword_suggest.fold`). */
export function foldKeyword(value: string): string {
  return value
    .toLowerCase()
    .replace(/ł/g, "l")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function splitHit(label: string, query: string): { hit: string; rest: string } {
  const q = foldKeyword(query);
  if (q && foldKeyword(label).startsWith(q)) {
    // Liczba znaków po złożeniu bywa inna tylko przy „ł”/akcentach złożonych —
    // dla pogrubienia wystarcza długość wpisanego tekstu.
    const n = Math.min(label.length, query.trim().length);
    return { hit: label.slice(0, n), rest: label.slice(n) };
  }
  return { hit: "", rest: label };
}

function matchesQuery(label: string, query: string): boolean {
  const q = foldKeyword(query);
  if (!q) return true;
  const folded = foldKeyword(label);
  return folded.startsWith(q) || folded.split(/[\s./#+\-()_,]+/).some((w) => w.startsWith(q));
}

const KIND_LABEL: Record<KeywordSuggestKind, string> = {
  skill: "Technologia",
  title: "Stanowisko",
  prefix: "Początek słowa",
};

export interface BuildOptionsInput {
  query: string;
  existing: readonly string[];
  context?: readonly KeywordContextItem[];
  recent?: readonly string[];
  response?: KeywordSuggestResponse | null;
  /** Tylko umiejętności (koszyki skilli) — bez stanowisk i wzorców. */
  skillsOnly?: boolean;
  limit?: number;
}

export function buildSuggestionOptions({
  query,
  existing,
  context = [],
  recent = [],
  response = null,
  skillsOnly = false,
  limit = 9,
}: BuildOptionsInput): SuggestionOption[] {
  const trimmed = query.trim();
  const used = new Set(existing.map(foldKeyword));
  const out: SuggestionOption[] = [];
  const push = (option: SuggestionOption) => {
    const key = foldKeyword(option.insert);
    if (!key || used.has(key)) return;
    used.add(key);
    out.push(option);
  };
  // Druga pozycja tej samej umiejętności: nazwa + warianty pisowni jednym
  // wyborem (decyzja 25.09.2026 — warianty dodaje przycisk, nigdy automat).
  // Warianty, które już są w polu, odpadają; bez nich pozycji nie ma.
  const pushVariants = (item: KeywordSuggestion) => {
    const variants = (item.variants ?? []).filter((v) => !used.has(foldKeyword(v)));
    if (variants.length === 0) return;
    out.push({
      key: `variants:${item.insert}`,
      insert: item.insert,
      hit: "",
      rest: `${item.label} + ${variants.join(", ")}`,
      note: "",
      kindLabel: "Z wariantami",
      count: null,
      group: "base",
      variants,
    });
  };

  for (const item of context) {
    if (!matchesQuery(item.label, trimmed)) continue;
    const { hit, rest } = splitHit(item.label, trimmed);
    push({
      key: `context:${item.label}`,
      insert: item.label,
      hit,
      rest,
      note: item.note ?? "",
      kindLabel: "Rekrutacja",
      count: null,
      group: "context",
    });
  }
  for (const word of recent) {
    if (!matchesQuery(word, trimmed)) continue;
    const { hit, rest } = splitHit(word, trimmed);
    push({
      key: `recent:${word}`,
      insert: word,
      hit,
      rest,
      note: "",
      kindLabel: "Ostatnio",
      count: null,
      group: "recent",
    });
  }
  if (trimmed && response) {
    for (const item of response.items) {
      if (skillsOnly && item.kind !== "skill") continue;
      const { hit, rest } = splitHit(item.label, trimmed);
      push({
        key: `base:${item.kind}:${item.insert}`,
        insert: item.insert,
        hit,
        rest,
        note: item.alias && !hit ? `(też: ${item.alias})` : "",
        kindLabel: KIND_LABEL[item.kind],
        count: item.count ?? null,
        group: "base",
      });
      if (item.kind === "skill") pushVariants(item);
    }
    if (!skillsOnly && response.wildcard) {
      push({
        key: `pattern:${response.wildcard.insert}`,
        insert: response.wildcard.insert,
        hit: response.wildcard.insert,
        rest: "",
        note: "każde słowo zaczynające się tak",
        kindLabel: KIND_LABEL.prefix,
        count: response.wildcard.count ?? null,
        group: "pattern",
      });
    }
  }
  if (trimmed.length >= 2) {
    push({
      key: `exact:${trimmed}`,
      insert: trimmed,
      hit: `„${trimmed}”`,
      rest: "",
      note: "dokładnie jak wpisane",
      kindLabel: "Słowo",
      count: null,
      group: "pattern",
    });
  }
  return out.slice(0, limit);
}

export function formatSuggestionCount(count: number | null): string {
  if (count == null) return "";
  return `~${count.toLocaleString("pl-PL")}`;
}

export async function fetchKeywordSuggestions(
  q: string,
  signal?: AbortSignal,
): Promise<KeywordSuggestResponse> {
  const { data } = await api.get<KeywordSuggestResponse>(KEYWORD_SUGGEST_ENDPOINT, {
    params: { q, limit: 6 },
    signal,
  });
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    wildcard: data?.wildcard ?? null,
  };
}

const CACHE_TTL_MS = 5 * 60 * 1000;
const cache = new Map<string, { at: number; data: KeywordSuggestResponse }>();

/** Tylko do testów — wyczyść pamięć podpowiedzi. */
export function clearKeywordSuggestCache(): void {
  cache.clear();
}

/**
 * Podpowiedzi z bazy dla pola z fokusem; 200 ms po ostatnim znaku, pamięć
 * 5 min na wpisany tekst. Bez react-query, bo pole żyje też w miejscach bez
 * `QueryClientProvider` (panel filtrów w testach, okna).
 */
export function useKeywordSuggestions(query: string, enabled: boolean) {
  const debounced = useDebouncedValue(query.trim(), 200);
  const key = foldKeyword(debounced);
  // Odpowiedź pamięta, dla jakiego tekstu przyszła — lista nigdy nie pokazuje
  // (ani nie wstawia Enterem) podpowiedzi do poprzedniego słowa.
  const [result, setResult] = useState<{ key: string; data: KeywordSuggestResponse } | null>(
    null,
  );
  useEffect(() => {
    if (!enabled || !key) return;
    const hit = cache.get(key);
    if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
      setResult({ key, data: hit.data });
      return;
    }
    const controller = new AbortController();
    fetchKeywordSuggestions(debounced, controller.signal)
      .then((result) => {
        cache.set(key, { at: Date.now(), data: result });
        if (!controller.signal.aborted) setResult({ key, data: result });
      })
      .catch(() => {
        // Podpowiedzi to dodatek: awaria zostawia listę bez pozycji z bazy.
      });
    return () => controller.abort();
  }, [enabled, key, debounced]);
  const current = foldKeyword(query.trim());
  return {
    data: enabled && result && result.key === current ? result.data : undefined,
  };
}
