/**
 * Zapytania edytora wymagań (`components/champion/RequirementRowsEditor`):
 * etykiety i dopuszczalność krytycznych, liczba osób w bazie, zamiana starych
 * pól na wiersze. Reguły: `lib/requirement-rows.ts`.
 */

import { useQueries, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { fetchCandidateListPage } from "@/components/v2/pages/candidate-list-query";
import {
  requiredRows,
  rowCriticalInfo,
  type RequirementRowForm,
  type RowCriticalResponse,
  type RowCriticalState,
  type StoredRequirementRow,
} from "@/lib/requirement-rows";
import { DEFAULT_FILTERS, filtersToApiParams } from "@/lib/url-filters";
import { useDebouncedValue } from "@/lib/use-debounced-value";

export function rowCriticalKey(rows: readonly (readonly string[])[], title: string) {
  return ["requirement-rows-critical", rows, title.trim()] as const;
}

/**
 * Etykiety wierszy obowiązkowych, to, które wolno oznaczyć jako krytyczne,
 * i podpowiedź z historii — dla listy, której jeszcze nie zapisano. Lista
 * zmienia się przy każdym słowie, więc zapytanie czeka na chwilę ciszy,
 * a odpowiedź dla starszej listy NIE jest oddawana jako bieżąca (`info: null`).
 */
export function useRowCriticalInfo(
  rows: readonly RequirementRowForm[],
  title: string,
  { enabled = true, debounceMs = 400 }: { enabled?: boolean; debounceMs?: number } = {},
): RowCriticalState {
  const required = requiredRows(rows);
  const key = JSON.stringify([required.map((row) => row.words), title.trim()]);
  const settled = useDebouncedValue(key, debounceMs);
  const [settledRows, settledTitle] = JSON.parse(settled) as [string[][], string];
  const query = useQuery({
    queryKey: rowCriticalKey(settledRows, settledTitle),
    enabled: enabled && settledRows.length > 0,
    staleTime: 5 * 60_000,
    queryFn: ({ signal }) =>
      api
        .post<RowCriticalResponse>(
          "/api/job-intake/critical-suggestion",
          { rows: settledRows, title: settledTitle || undefined },
          { signal },
        )
        .then((r) => r.data),
  });
  const current = settled === key;
  if (required.length === 0)
    return { info: {}, isLoading: false, isError: false, retry: () => undefined };
  return {
    info: current && query.data ? rowCriticalInfo(rows, query.data) : null,
    isLoading: enabled && (!current || query.isPending),
    isError: current && query.isError,
    retry: () => void query.refetch(),
  };
}

/** Ile osób (aktywni i pasywni) ma słowo z KAŻDEGO z wierszy — jak „Szukaj ręcznie”. */
async function countPeople(
  rows: string[][],
  exclude: string[],
  signal?: AbortSignal,
): Promise<number | null> {
  const params = filtersToApiParams(
    { ...DEFAULT_FILTERS, status: ["active", "passive"], qAny: rows, qNone: exclude },
    1,
    { page_size: 1 },
  );
  const data = await fetchCandidateListPage<{ total?: unknown }>(params, signal);
  return typeof data?.total === "number" ? data.total : null;
}

export interface RowCounts {
  /** Po kluczu wiersza: liczba osób, `null` = nie policzono, brak klucza = liczę. */
  perRow: Record<string, number | null>;
  /** Wszystkie wiersze obowiązkowe naraz. */
  required: number | null | undefined;
  /** Same krytyczne (gdy są). */
  critical: number | null | undefined;
  failed: boolean;
}

/**
 * Liczby przy wierszach: każdy wiersz obowiązkowy osobno (zbyt wąskie słowo
 * widać od razu — „bankowości” 55 osób, „bankow*” 323), wszystkie naraz i same
 * krytyczne. `undefined` = jeszcze liczę, `null` = serwer nie podał liczby.
 */
export function useRowCounts(
  rows: readonly RequirementRowForm[],
  exclude: readonly string[],
  enabled: boolean,
): RowCounts {
  const snapshot = useDebouncedValue(
    JSON.stringify({
      rows: requiredRows(rows).map((row) => ({
        key: row.key,
        words: row.words,
        critical: row.level === "critical",
      })),
      exclude,
    }),
    600,
  );
  const settled = JSON.parse(snapshot) as {
    rows: { key: string; words: string[]; critical: boolean }[];
    exclude: string[];
  };
  const perRowQueries = useQueries({
    queries: settled.rows.map((row) => ({
      queryKey: ["requirement-row-count", row.words],
      enabled,
      staleTime: 5 * 60_000,
      queryFn: ({ signal }: { signal?: AbortSignal }) => countPeople([row.words], [], signal),
    })),
  });
  const allWords = settled.rows.map((row) => row.words);
  const criticalWords = settled.rows.filter((row) => row.critical).map((row) => row.words);
  const required = useQuery({
    queryKey: ["requirement-rows-count", allWords, settled.exclude],
    enabled: enabled && allWords.length > 0,
    staleTime: 60_000,
    queryFn: ({ signal }) => countPeople(allWords, settled.exclude, signal),
  });
  const critical = useQuery({
    queryKey: ["requirement-rows-count", criticalWords, settled.exclude],
    enabled:
      enabled && criticalWords.length > 0 && criticalWords.length < allWords.length,
    staleTime: 60_000,
    queryFn: ({ signal }) => countPeople(criticalWords, settled.exclude, signal),
  });
  const perRow: Record<string, number | null> = {};
  settled.rows.forEach((row, index) => {
    const query = perRowQueries[index];
    if (query?.isSuccess) perRow[row.key] = query.data;
    else if (query?.isError) perRow[row.key] = null;
  });
  return {
    perRow,
    required: required.isSuccess ? required.data : required.isError ? null : undefined,
    critical:
      criticalWords.length === 0
        ? undefined
        : criticalWords.length === allWords.length
          ? required.isSuccess
            ? required.data
            : undefined
          : critical.isSuccess
            ? critical.data
            : critical.isError
              ? null
              : undefined,
    failed: required.isError,
  };
}

export interface LegacyRowsResult {
  rows: StoredRequirementRow[];
  /** Zdania klienta, które nie są słowami kluczowymi — nie filtrują kandydatów. */
  descriptive: string[];
  /** Delivery Lead wybrał wcześniej „Brak krytycznych”. */
  no_critical: boolean;
}

/** Stare pola (must, nice, wiersze wyszukiwania) → wiersze; niczego nie zapisuje. */
export function fetchRowsFromLegacy(body: {
  must: string[];
  nice: string[];
  requirements: string[][];
  critical: string[] | null;
}): Promise<LegacyRowsResult> {
  return api
    .post<LegacyRowsResult>("/api/job-intake/requirement-rows", body)
    .then((r) => r.data);
}
