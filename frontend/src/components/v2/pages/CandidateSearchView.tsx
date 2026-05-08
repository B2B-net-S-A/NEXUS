"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Loader2, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FiltersPanel } from "@/components/v2/filters/FiltersPanel";
import {
  candidateSearchApi,
  type CandidateSearchItem,
  type CandidateSearchRequest,
  type CandidateSearchResponse,
  type SortMode,
} from "@/lib/candidate-search-api";

const DEFAULT_REQUEST: CandidateSearchRequest = {
  q: null,
  q_all: [],
  q_any: [],
  q_none: [],
  competence_category_ids: [],
  skills_must: [],
  skills_any: [],
  skills_none: [],
  languages: [],
  location_cities: [],
  status: [],
  availability_status: [],
  tags: [],
  sort: "relevance",
  page: 1,
  page_size: 50,
};

interface CandidateSearchViewProps {
  /** Optional initial overrides — used by the job-context tab to prefill. */
  initial?: Partial<CandidateSearchRequest>;
  /** Renders a "Wstecz" link if provided. */
  backHref?: string;
}

/**
 * Standalone view for the manual CV search V2.
 *
 * Owns the request state, debounces user edits, and renders results below
 * the filter panel. The UI intentionally mirrors the structure of the AI
 * proposals tab so users moving between AI and manual search find the same
 * row layout (avatar, name, CC chip, skills, salary).
 */
export function CandidateSearchView({
  initial,
  backHref,
}: CandidateSearchViewProps) {
  const [request, setRequest] = useState<CandidateSearchRequest>({
    ...DEFAULT_REQUEST,
    ...initial,
  });
  const [data, setData] = useState<CandidateSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounce search by 300ms — typing in the free-text input shouldn't fire
  // a roundtrip per keystroke. The page resets to 1 on any non-page edit.
  useEffect(() => {
    const handle = setTimeout(() => {
      let cancelled = false;
      setLoading(true);
      setError(null);
      candidateSearchApi
        .search(request)
        .then((resp) => {
          if (!cancelled) setData(resp);
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : "Wyszukiwanie nie powiodło się");
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }, 300);
    return () => clearTimeout(handle);
  }, [request]);

  const ccCounts = useMemo(() => {
    const map: Record<number, number> = {};
    for (const f of data?.facets.competence_categories ?? []) {
      map[f.id] = f.count;
    }
    return map;
  }, [data]);

  const setRequestPatch = (next: CandidateSearchRequest) => {
    // Reset page to 1 unless caller is explicitly paging.
    setRequest({ ...next, page: 1 });
  };

  const setSort = (sort: SortMode) => {
    setRequest({ ...request, sort, page: 1 });
  };

  const setPage = (page: number) => {
    setRequest({ ...request, page });
  };

  const totalPages =
    data && data.page_size > 0 ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {backHref && (
            <Button asChild variant="ghost" size="sm" className="gap-1">
              <Link href={backHref}>
                <ArrowLeft className="h-4 w-4" />
                Wstecz
              </Link>
            </Button>
          )}
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <Search className="h-5 w-5" />
            Wyszukiwanie kandydatów
          </h1>
        </div>
        {data && (
          <div className="text-sm text-zinc-500 dark:text-zinc-400 tabular-nums">
            {data.total} {data.total === 1 ? "wynik" : "wyniki"} ·{" "}
            {data.meta.took_ms} ms
          </div>
        )}
      </header>

      <FiltersPanel value={request} onChange={setRequestPatch} ccCounts={ccCounts} />

      {/* Sort + status row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-zinc-500 dark:text-zinc-400">Sortuj:</span>
          {(
            [
              ["relevance", "Trafność"],
              ["recent", "Najnowsi"],
              ["name", "Alfabetycznie"],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              onClick={() => setSort(k)}
              className={
                request.sort === k
                  ? "rounded-md bg-violet-50 px-2 py-1 text-violet-700 dark:bg-violet-900/40 dark:text-violet-200"
                  : "rounded-md px-2 py-1 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              }
            >
              {label}
            </button>
          ))}
        </div>
        {loading && (
          <span className="flex items-center gap-1 text-xs text-zinc-500">
            <Loader2 className="h-3 w-3 animate-spin" />
            Ładowanie…
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200">
          {error}
        </div>
      )}

      {/* Result rows */}
      <ul className="divide-y rounded-lg border bg-card dark:border-zinc-800">
        {data?.items.length === 0 && !loading && (
          <li className="p-6 text-center text-sm text-zinc-500 dark:text-zinc-400">
            Brak wyników. Zmień filtry lub poszerz query.
          </li>
        )}
        {data?.items.map((c) => (
          <CandidateSearchRow key={c.id} item={c} />
        ))}
      </ul>

      {/* Pagination */}
      {data && data.total > data.page_size && (
        <div className="flex items-center justify-between text-sm">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={data.page <= 1 || loading}
            onClick={() => setPage(data.page - 1)}
          >
            Poprzednia
          </Button>
          <span className="text-zinc-500 tabular-nums dark:text-zinc-400">
            Strona {data.page} / {totalPages}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={data.page >= totalPages || loading}
            onClick={() => setPage(data.page + 1)}
          >
            Następna
          </Button>
        </div>
      )}
    </div>
  );
}

function CandidateSearchRow({ item }: { item: CandidateSearchItem }) {
  const skillsList = Array.isArray(item.skills)
    ? (item.skills as Array<string | { name?: string }>)
    : [];
  const skillNames = skillsList
    .map((s) => (typeof s === "string" ? s : s.name ?? null))
    .filter((s): s is string => Boolean(s))
    .slice(0, 6);

  return (
    <li className="flex items-start gap-3 p-3 hover:bg-zinc-50 dark:hover:bg-zinc-900/50">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Link
            href={`/candidates/${item.id}`}
            className="font-medium hover:underline"
          >
            {item.name} {item.lastname}
          </Link>
          {item.competence_category && (
            <Badge variant="secondary">{item.competence_category}</Badge>
          )}
          {item.is_champion && (
            <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
              Champion
            </Badge>
          )}
          {item.years_it_experience !== null && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              {item.years_it_experience} lat IT
            </span>
          )}
          {item.location && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              {item.location}
            </span>
          )}
        </div>
        {skillNames.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {skillNames.map((s) => (
              <span
                key={s}
                className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
              >
                {s}
              </span>
            ))}
          </div>
        )}
        {item.ai_summary && (
          <p className="mt-1 line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400">
            {item.ai_summary}
          </p>
        )}
      </div>
      <div className="text-right text-xs text-zinc-500 dark:text-zinc-400 tabular-nums whitespace-nowrap">
        {item.salary_expectation && (
          <div>
            {item.salary_expectation.toLocaleString("pl-PL")}{" "}
            {item.salary_currency ?? "PLN"}
          </div>
        )}
        {item.availability_status && (
          <div className="capitalize">
            {item.availability_status.replace(/_/g, " ")}
          </div>
        )}
      </div>
    </li>
  );
}
