"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Bookmark, Loader2, Plus, Search, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AiStatusBanner } from "@/components/jobs/AiStatusBanner";
import { FiltersPanel } from "@/components/v2/filters/FiltersPanel";
import {
  candidateSearchApi,
  proposalsBulkApi,
  savedSearchesApi,
  type BulkProposalsResponse,
  type CandidateSearchItem,
  type CandidateSearchRequest,
  type CandidateSearchResponse,
  type SavedSearchOut,
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
  search_mode: "boolean",
};

interface CandidateSearchViewProps {
  /** Optional initial overrides – used by the job-context tab to prefill. */
  initial?: Partial<CandidateSearchRequest>;
  /** Renders a "Wstecz" link if provided. */
  backHref?: string;
  /**
   * Job context – when set, results carry checkboxes and a sticky bulk-add
   * bar that posts to ``POST /api/jobs/{id}/proposals/bulk``. Also forces
   * ``exclude_in_job_id`` so already-added candidates don't appear.
   */
  addToJob?: { id: number; title: string };
  /** Called after a successful bulk-add so the parent can refresh the AI tab. */
  onBulkAdded?: (resp: BulkProposalsResponse) => void;
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
  addToJob,
  onBulkAdded,
}: CandidateSearchViewProps) {
  const [request, setRequest] = useState<CandidateSearchRequest>({
    ...DEFAULT_REQUEST,
    ...(addToJob ? { exclude_in_job_id: addToJob.id } : {}),
    ...initial,
  });
  const [data, setData] = useState<CandidateSearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkPending, setBulkPending] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkProposalsResponse | null>(null);

  // Saved searches – list refetched after every mutation.
  const [savedSearches, setSavedSearches] = useState<SavedSearchOut[]>([]);
  const [saveDraftOpen, setSaveDraftOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [savePinToJob, setSavePinToJob] = useState(true);
  const [savePending, setSavePending] = useState(false);

  const refreshSavedSearches = useCallback(() => {
    savedSearchesApi
      .list({
        entity: "candidates",
        pinned_to_job_id: addToJob?.id,
        only_mine: addToJob ? undefined : true,
      })
      .then(setSavedSearches)
      .catch(() => setSavedSearches([]));
  }, [addToJob?.id]);

  useEffect(() => {
    refreshSavedSearches();
  }, [refreshSavedSearches]);

  const toggleSelect = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const clearSelection = () => setSelected(new Set());

  const loadSavedSearch = (ss: SavedSearchOut) => {
    // Filters were stored as a CandidateSearchRequest dump – restore but
    // never carry over paging or job-context exclusion (those are owned by
    // the current view).
    const filters = ss.filters as Partial<CandidateSearchRequest>;
    setRequest({
      ...DEFAULT_REQUEST,
      ...(addToJob ? { exclude_in_job_id: addToJob.id } : {}),
      ...filters,
      page: 1,
    });
  };

  const saveCurrentSearch = async () => {
    const name = saveName.trim();
    if (!name) return;
    setSavePending(true);
    try {
      // Strip transient fields (page, exclude_in_job_id) – they're not part
      // of the user's intent, just current view state.
      const { page: _page, exclude_in_job_id: _excl, ...rest } = request;
      void _page;
      void _excl;
      await savedSearchesApi.create({
        name,
        entity: "candidates",
        filters: rest as unknown as Record<string, unknown>,
        pinned_to_job_id: savePinToJob ? addToJob?.id ?? null : null,
      });
      setSaveDraftOpen(false);
      setSaveName("");
      refreshSavedSearches();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Zapisanie nie powiodło się");
    } finally {
      setSavePending(false);
    }
  };

  const deleteSavedSearch = async (id: number) => {
    try {
      await savedSearchesApi.remove(id);
      refreshSavedSearches();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Usunięcie nie powiodło się");
    }
  };

  const submitBulk = async () => {
    if (!addToJob || selected.size === 0) return;
    setBulkPending(true);
    setError(null);
    try {
      const resp = await proposalsBulkApi.add(addToJob.id, {
        candidate_ids: Array.from(selected),
      });
      setBulkResult(resp);
      clearSelection();
      // Re-run the search so newly added candidates drop out (excluded).
      setRequest((r) => ({ ...r }));
      onBulkAdded?.(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk add nie powiódł się");
    } finally {
      setBulkPending(false);
    }
  };

  // Debounce search by 300ms – typing in the free-text input shouldn't fire
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
            <Link
              href={backHref}
              className={buttonVariants({ variant: "ghost", size: "sm" })}
            >
              <ArrowLeft className="h-4 w-4" />
              Wstecz
            </Link>
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

      {data?.meta && data.meta.ai_status !== "ok" && (
        <AiStatusBanner status={data.meta.ai_status} />
      )}

      <FiltersPanel value={request} onChange={setRequestPatch} ccCounts={ccCounts} />

      {/* Saved searches strip */}
      {(savedSearches.length > 0 || saveDraftOpen) && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-zinc-500 dark:text-zinc-400 font-medium">
            Zapisane:
          </span>
          {savedSearches.map((ss) => (
            <span
              key={ss.id}
              className="group inline-flex items-center gap-1 rounded-md border bg-white px-2 py-1 dark:bg-zinc-900 dark:border-zinc-700"
            >
              <button
                type="button"
                onClick={() => loadSavedSearch(ss)}
                className="hover:text-violet-700 dark:hover:text-violet-300"
              >
                {ss.name}
              </button>
              {ss.pinned_to_job_id !== null && (
                <Badge variant="neutral" className="h-4 px-1 text-[10px]">
                  pin
                </Badge>
              )}
              <button
                type="button"
                aria-label={`Usuń ${ss.name}`}
                onClick={() => deleteSavedSearch(ss.id)}
                className="opacity-0 group-hover:opacity-100 text-zinc-400 hover:text-rose-600"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </span>
          ))}
          {!saveDraftOpen ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setSaveDraftOpen(true)}
              className="h-7 gap-1 text-xs"
            >
              <Bookmark className="h-3 w-3" />
              Zapisz wyszukiwanie
            </Button>
          ) : (
            <span className="inline-flex items-center gap-1.5">
              <Input
                autoFocus
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void saveCurrentSearch();
                  }
                  if (e.key === "Escape") setSaveDraftOpen(false);
                }}
                placeholder="Nazwa…"
                className="h-7 w-40 text-xs"
                maxLength={100}
              />
              {addToJob && (
                <label className="flex items-center gap-1 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={savePinToJob}
                    onChange={(e) => setSavePinToJob(e.target.checked)}
                    className="h-3 w-3"
                  />
                  Pin do "{addToJob.title}"
                </label>
              )}
              <Button
                size="sm"
                className="h-7 text-xs"
                onClick={saveCurrentSearch}
                disabled={savePending || saveName.trim().length === 0}
              >
                {savePending ? <Loader2 className="h-3 w-3 animate-spin" /> : "Zapisz"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={() => setSaveDraftOpen(false)}
                disabled={savePending}
              >
                Anuluj
              </Button>
            </span>
          )}
        </div>
      )}
      {savedSearches.length === 0 && !saveDraftOpen && (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => setSaveDraftOpen(true)}
          className="h-7 gap-1 text-xs self-start"
        >
          <Bookmark className="h-3 w-3" />
          Zapisz to wyszukiwanie
        </Button>
      )}

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

      {bulkResult && (
        <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
          Dodano {bulkResult.total_added} kandydatów do requestu „{addToJob?.title}".
          {bulkResult.total_skipped > 0 && (
            <> Pominięto {bulkResult.total_skipped} (już w jobie / blacklist).</>
          )}
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
          <CandidateSearchRow
            key={c.id}
            item={c}
            selectable={Boolean(addToJob)}
            selected={selected.has(c.id)}
            onToggleSelect={() => toggleSelect(c.id)}
          />
        ))}
      </ul>

      {/* Sticky bulk-add bar – only when in job context */}
      {addToJob && selected.size > 0 && (
        <div className="sticky bottom-4 z-10 mx-auto flex w-fit items-center gap-3 rounded-full border bg-zinc-900 px-4 py-2 text-sm text-zinc-50 shadow-lg dark:bg-zinc-100 dark:text-zinc-900">
          <span className="tabular-nums">
            Wybrano <strong>{selected.size}</strong>
          </span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 text-xs hover:bg-zinc-700 dark:hover:bg-zinc-200"
            onClick={clearSelection}
            disabled={bulkPending}
          >
            Wyczyść
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-7 gap-1 bg-violet-600 text-white hover:bg-violet-500"
            onClick={submitBulk}
            disabled={bulkPending}
          >
            {bulkPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Plus className="h-3 w-3" />
            )}
            Dodaj do „{addToJob.title}"
          </Button>
        </div>
      )}

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

interface CandidateSearchRowProps {
  item: CandidateSearchItem;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
}

function CandidateSearchRow({
  item,
  selectable = false,
  selected = false,
  onToggleSelect,
}: CandidateSearchRowProps) {
  const skillsList = Array.isArray(item.skills)
    ? (item.skills as Array<string | { name?: string }>)
    : [];
  const skillNames = skillsList
    .map((s) => (typeof s === "string" ? s : s.name ?? null))
    .filter((s): s is string => Boolean(s))
    .slice(0, 6);

  return (
    <li className="flex items-start gap-3 p-3 hover:bg-zinc-50 dark:hover:bg-zinc-900/50">
      {selectable && (
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          aria-label={`Zaznacz ${item.name} ${item.lastname}`}
          className="mt-1 h-4 w-4 rounded border-zinc-300 text-violet-600 focus:ring-violet-500"
        />
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Link
            href={`/candidates/${item.id}`}
            className="font-medium hover:underline"
          >
            {item.name} {item.lastname}
          </Link>
          {item.competence_category && (
            <Badge variant="neutral">{item.competence_category}</Badge>
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
