"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Bookmark,
  ChevronDown,
  ChevronUp,
  Loader2,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AiStatusBanner } from "@/components/jobs/AiStatusBanner";
import { FiltersPanel } from "@/components/v2/filters/FiltersPanel";
import {
  candidateSearchApi,
  proposalsBulkApi,
  savedSearchesApi,
  type AssignableStage,
  type BulkProposalsResponse,
  type CandidateSearchItem,
  type CandidateSearchRequest,
  type CandidateSearchResponse,
  type SavedSearchOut,
  type SearchDiagnosticsResponse,
  type SortMode,
} from "@/lib/candidate-search-api";
import { formatCandidateLocation } from "@/components/v2/pages/candidate-list-helpers";
import {
  formatReasonCounts,
  summarizeBulkResult,
} from "@/lib/bulk-result-summary";
import {
  hasBreakdownDetail,
  summarizeBreakdown,
  type MatchBreakdown,
} from "@/lib/match-breakdown";

const DEFAULT_REQUEST: CandidateSearchRequest = {
  q: null,
  q_all: [],
  q_any: [],
  q_any_groups: [],
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

/**
 * Parse a comma/newline-separated tag input into a clean list: trimmed,
 * case-insensitively de-duplicated, capped at the backend's 20-tag limit.
 */
export function parseTagInput(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(/[,\n]/)) {
    const tag = part.trim();
    if (!tag) continue;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
    if (out.length >= 20) break;
  }
  return out;
}

interface CandidateSearchViewProps {
  /** Optional initial overrides — used by the job-context tab to prefill. */
  initial?: Partial<CandidateSearchRequest>;
  /** Renders a "Wstecz" link if provided. */
  backHref?: string;
  /**
   * Job context — when set, results carry checkboxes and a sticky bulk-add
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
  const [diagnostics, setDiagnostics] =
    useState<SearchDiagnosticsResponse | null>(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const [matchScores, setMatchScores] = useState<Record<string, number>>({});
  const [matchBreakdowns, setMatchBreakdowns] = useState<
    Record<string, MatchBreakdown>
  >({});
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [bulkPending, setBulkPending] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkProposalsResponse | null>(null);
  const [bulkOptionsOpen, setBulkOptionsOpen] = useState(false);
  const [bulkNote, setBulkNote] = useState("");
  const [bulkTagsInput, setBulkTagsInput] = useState("");
  const [bulkStageId, setBulkStageId] = useState<number | "">("");
  const [assignableStages, setAssignableStages] = useState<AssignableStage[]>([]);

  // Saved searches — list refetched after every mutation.
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

  // Load the job's assignable (non-terminal) stages once, for the bulk-add
  // target-stage picker. Best-effort: on failure the picker just isn't shown.
  useEffect(() => {
    if (!addToJob) return;
    let cancelled = false;
    proposalsBulkApi
      .assignableStages(addToJob.id)
      .then((s) => {
        if (!cancelled) setAssignableStages(s);
      })
      .catch(() => {
        if (!cancelled) setAssignableStages([]);
      });
    return () => {
      cancelled = true;
    };
  }, [addToJob]);

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
    // Filters were stored as a CandidateSearchRequest dump — restore but
    // never carry over paging or job-context exclusion (those are owned by
    // the current view).
    const filters = ss.filters as Partial<CandidateSearchRequest>;
    clearSelection();
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
      // Strip transient fields (page, exclude_in_job_id) — they're not part
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
      const note = bulkNote.trim();
      const tags = parseTagInput(bulkTagsInput);
      const resp = await proposalsBulkApi.add(addToJob.id, {
        candidate_ids: Array.from(selected),
        ...(typeof bulkStageId === "number"
          ? { initial_stage_def_id: bulkStageId }
          : {}),
        ...(note ? { note } : {}),
        ...(tags.length ? { tags } : {}),
      });
      setBulkResult(resp);
      clearSelection();
      setBulkNote("");
      setBulkTagsInput("");
      setBulkStageId("");
      setBulkOptionsOpen(false);
      // Re-run the search so newly added candidates drop out (excluded).
      setRequest((r) => ({ ...r }));
      onBulkAdded?.(resp);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bulk add nie powiódł się");
    } finally {
      setBulkPending(false);
    }
  };

  // Debounce search by 300ms — typing in the free-text input shouldn't fire
  // a roundtrip per keystroke. The page resets to 1 on any non-page edit.
  //
  // ``cancelled`` lives in the EFFECT scope (not inside setTimeout) so a
  // superseded, still-in-flight request can never overwrite newer results —
  // the previous effect's cleanup flips its own flag before the next runs.
  useEffect(() => {
    let cancelled = false;
    const handle = setTimeout(() => {
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
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [request]);

  // Exclusion waterfall — only when a COMPLETED search returned nothing (it runs
  // several cumulative COUNT queries, so never fire it on a non-empty result).
  // Keyed on `data`: fires once per empty result, using the request that
  // produced it.
  useEffect(() => {
    if (!data || data.total > 0) {
      setDiagnostics(null);
      return;
    }
    let cancelled = false;
    setDiagLoading(true);
    candidateSearchApi
      .diagnostics(request)
      .then((d) => {
        if (!cancelled) setDiagnostics(d);
      })
      .catch(() => {
        if (!cancelled) setDiagnostics(null);
      })
      .finally(() => {
        if (!cancelled) setDiagLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // Match scores (job context only): read-only cached hybrid scores for the
  // visible page. Best-effort — only candidates already scored (by kanban /
  // recommendations) get a badge; this never computes, so it can't be slow or
  // pollute the shared cache.
  useEffect(() => {
    if (!addToJob || !data || data.items.length === 0) {
      setMatchScores({});
      setMatchBreakdowns({});
      return;
    }
    let cancelled = false;
    candidateSearchApi
      .matchScores(
        addToJob.id,
        data.items.map((c) => c.id),
      )
      .then((s) => {
        if (!cancelled) {
          setMatchScores(s.scores);
          setMatchBreakdowns(s.breakdowns);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMatchScores({});
          setMatchBreakdowns({});
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, addToJob]);

  const ccCounts = useMemo(() => {
    const map: Record<number, number> = {};
    for (const f of data?.facets.competence_categories ?? []) {
      map[f.id] = f.count;
    }
    return map;
  }, [data]);

  const setRequestPatch = (next: CandidateSearchRequest) => {
    // Reset page to 1 unless caller is explicitly paging. Changing the filter
    // set invalidates the current selection (checked rows may no longer be in
    // the result set), so drop it — paging keeps selection (see ``setPage``).
    clearSelection();
    setRequest({ ...next, page: 1 });
  };

  const setSort = (sort: SortMode) => {
    clearSelection();
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
                className="hover:text-primary"
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
                  ? "rounded-md bg-primary/10 px-2 py-1 text-primary"
                  : "rounded-md px-2 py-1 text-muted-foreground hover:bg-muted"
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

      {bulkResult &&
        (() => {
          const summary = summarizeBulkResult(bulkResult);
          return (
            <div className="space-y-1 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
              <div>
                Dodano {summary.added} kandydatów do requestu „{addToJob?.title}
                ".
              </div>
              {summary.warnings.length > 0 && (
                <div className="text-amber-700 dark:text-amber-300">
                  ⚠ Z ostrzeżeniem: {formatReasonCounts(summary.warnings)}.
                </div>
              )}
              {summary.skipped.length > 0 && (
                <div className="text-zinc-600 dark:text-zinc-400">
                  Pominięto {bulkResult.total_skipped}:{" "}
                  {formatReasonCounts(summary.skipped)}.
                </div>
              )}
            </div>
          );
        })()}

      {/* Result rows */}
      <ul className="divide-y rounded-lg border bg-card dark:border-zinc-800">
        {data?.items.length === 0 && !loading && (
          <li className="p-4">
            <ExclusionWaterfall
              diagnostics={diagnostics}
              loading={diagLoading}
            />
          </li>
        )}
        {data?.items.map((c) => (
          <CandidateSearchRow
            key={c.id}
            item={c}
            selectable={Boolean(addToJob)}
            selected={selected.has(c.id)}
            onToggleSelect={() => toggleSelect(c.id)}
            score={matchScores[String(c.id)]}
            breakdown={matchBreakdowns[String(c.id)]}
          />
        ))}
      </ul>

      {/* Sticky bulk-add bar — only when in job context */}
      {addToJob && selected.size > 0 && (
        <div className="sticky bottom-4 z-10 mx-auto flex w-fit max-w-full flex-col items-center gap-2">
          {bulkOptionsOpen && (
            <div className="w-80 max-w-full space-y-2 rounded-xl border bg-card p-3 text-left shadow-lg dark:border-zinc-800">
              {assignableStages.length > 0 && (
                <div className="space-y-1">
                  <label
                    htmlFor="bulk-stage"
                    className="text-xs font-medium text-zinc-600 dark:text-zinc-300"
                  >
                    Etap docelowy
                  </label>
                  <select
                    id="bulk-stage"
                    value={bulkStageId === "" ? "" : String(bulkStageId)}
                    onChange={(e) =>
                      setBulkStageId(
                        e.target.value === "" ? "" : Number(e.target.value),
                      )
                    }
                    className="w-full rounded-md border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring dark:border-zinc-700"
                  >
                    <option value="">Domyślny (pierwszy etap)</option>
                    {assignableStages.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div className="space-y-1">
                <label
                  htmlFor="bulk-note"
                  className="text-xs font-medium text-zinc-600 dark:text-zinc-300"
                >
                  Notatka (dołączona do każdego dodanego kandydata)
                </label>
                <textarea
                  id="bulk-note"
                  value={bulkNote}
                  onChange={(e) => setBulkNote(e.target.value)}
                  rows={2}
                  maxLength={2000}
                  placeholder="Opcjonalna wspólna notatka…"
                  className="w-full resize-none rounded-md border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring dark:border-zinc-700"
                />
              </div>
              <div className="space-y-1">
                <label
                  htmlFor="bulk-tags"
                  className="text-xs font-medium text-zinc-600 dark:text-zinc-300"
                >
                  Tagi (oddziel przecinkami)
                </label>
                <Input
                  id="bulk-tags"
                  value={bulkTagsInput}
                  onChange={(e) => setBulkTagsInput(e.target.value)}
                  placeholder="np. linkedin, pilne"
                  className="h-8 text-xs"
                />
              </div>
            </div>
          )}
          <div className="flex w-fit items-center gap-3 rounded-full border bg-zinc-900 px-4 py-2 text-sm text-zinc-50 shadow-lg dark:bg-zinc-100 dark:text-zinc-900">
            <span className="tabular-nums">
              Wybrano <strong>{selected.size}</strong>
            </span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 gap-1 text-xs hover:bg-zinc-700 dark:hover:bg-zinc-200"
              onClick={() => setBulkOptionsOpen((o) => !o)}
              disabled={bulkPending}
            >
              Notatka i tagi
              {bulkOptionsOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronUp className="h-3 w-3" />
              )}
              {(bulkNote.trim() ||
                bulkTagsInput.trim() ||
                bulkStageId !== "") && (
                <span className="ml-0.5 h-1.5 w-1.5 rounded-full bg-primary" />
              )}
            </Button>
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
              className="h-7 gap-1 bg-primary text-primary-foreground hover:bg-primary/90"
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
  /** Cached hybrid match score (0-100) vs. the job, if one exists. */
  score?: number;
  /** Cached score breakdown (per-layer points + matched/gap skills). */
  breakdown?: MatchBreakdown;
}

export function scoreBadgeClass(score: number): string {
  if (score >= 70)
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200";
  if (score >= 40)
    return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200";
  return "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
}

function CandidateSearchRow({
  item,
  selectable = false,
  selected = false,
  onToggleSelect,
  score,
  breakdown,
}: CandidateSearchRowProps) {
  const [showBreakdown, setShowBreakdown] = useState(false);
  const canExpand = typeof score === "number" && hasBreakdownDetail(breakdown);
  const skillsList = Array.isArray(item.skills)
    ? (item.skills as Array<string | { name?: string }>)
    : [];
  const skillNames = skillsList
    .map((s) => (typeof s === "string" ? s : s.name ?? null))
    .filter((s): s is string => Boolean(s))
    .slice(0, 6);
  const formattedLocation = formatCandidateLocation(item.location);

  return (
    <li className="p-3 hover:bg-zinc-50 dark:hover:bg-zinc-900/50">
      <div className="flex items-start gap-3">
      {selectable && (
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          aria-label={`Zaznacz ${item.name} ${item.lastname}`}
          className="mt-1 h-4 w-4 rounded border-input text-primary focus:ring-ring"
        />
      )}
      {typeof score === "number" && (
        <button
          type="button"
          onClick={() => canExpand && setShowBreakdown((v) => !v)}
          aria-expanded={canExpand ? showBreakdown : undefined}
          title={
            canExpand
              ? "Pokaż dopasowanie do requestu"
              : "Dopasowanie do requestu (hybrydowy wynik 0-100)"
          }
          className={`mt-0.5 inline-flex h-6 w-9 shrink-0 items-center justify-center rounded-md text-xs font-semibold tabular-nums ${scoreBadgeClass(
            score,
          )} ${
            canExpand
              ? "cursor-pointer hover:ring-1 hover:ring-ring"
              : "cursor-default"
          }`}
        >
          {score}
        </button>
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
          {formattedLocation && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              {formattedLocation}
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
      </div>
      {showBreakdown && canExpand && breakdown && (
        <MatchScoreDetail breakdown={breakdown} />
      )}
    </li>
  );
}

function MatchScoreDetail({ breakdown }: { breakdown: MatchBreakdown }) {
  const s = summarizeBreakdown(breakdown);
  const Chips = ({ items, tone }: { items: string[]; tone: "ok" | "gap" }) => (
    <>
      {items.map((t) => (
        <span
          key={t}
          className={`rounded px-1.5 py-0.5 text-xs ${
            tone === "ok"
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"
              : "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200"
          }`}
        >
          {t}
        </span>
      ))}
    </>
  );
  return (
    <div className="ml-12 mt-2 space-y-2 rounded-lg border bg-muted/40 p-3 dark:border-zinc-800">
      {s.layers.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-600 dark:text-zinc-300">
          {s.layers.map((l) => (
            <span key={l.key} className="tabular-nums">
              {l.label}{" "}
              <strong>
                {l.points}/{l.max}
              </strong>
            </span>
          ))}
        </div>
      )}
      {(s.matchedMust.length > 0 || s.gapMust.length > 0) && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Wymagane:
          </span>
          <Chips items={s.matchedMust} tone="ok" />
          <Chips items={s.gapMust} tone="gap" />
        </div>
      )}
      {(s.matchedNice.length > 0 || s.gapNice.length > 0) && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-1 text-xs font-medium text-zinc-500 dark:text-zinc-400">
            Mile widziane:
          </span>
          <Chips items={s.matchedNice} tone="ok" />
          <Chips items={s.gapNice} tone="gap" />
        </div>
      )}
    </div>
  );
}

interface ExclusionWaterfallProps {
  diagnostics: SearchDiagnosticsResponse | null;
  loading: boolean;
}

/**
 * Empty-state diagnostics: shows how each filter narrowed the candidate pool,
 * highlighting the stage where the count first hit zero (SEARCH-P1-04).
 */
export function ExclusionWaterfall({
  diagnostics,
  loading,
}: ExclusionWaterfallProps) {
  if (loading && !diagnostics) {
    return (
      <div className="flex items-center justify-center gap-2 py-2 text-sm text-zinc-500 dark:text-zinc-400">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Analizuję, który filtr zawęził wyniki…
      </div>
    );
  }
  if (!diagnostics || diagnostics.stages.length === 0) {
    return (
      <div className="py-2 text-center text-sm text-zinc-500 dark:text-zinc-400">
        Brak wyników. Zmień filtry lub poszerz zapytanie.
      </div>
    );
  }

  const rows = [
    { key: "__base__", label: "Wszyscy kandydaci", count: diagnostics.base_count },
    ...diagnostics.stages,
  ];
  const maxCount = Math.max(diagnostics.base_count, 1);

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">
        Brak wyników — na którym filtrze odpadli kandydaci?
      </p>
      <ul className="space-y-1">
        {rows.map((s, i) => {
          const isCulprit = s.key === diagnostics.first_zeroing_stage;
          const isZero = s.count === 0;
          const pct = Math.max(2, Math.round((s.count / maxCount) * 100));
          return (
            <li key={s.key} className="flex items-center gap-2 text-xs">
              <span
                className={`w-44 shrink-0 truncate text-right ${
                  i === 0 ? "font-medium" : "text-zinc-600 dark:text-zinc-400"
                }`}
              >
                {s.label}
              </span>
              <span className="relative h-4 flex-1 overflow-hidden rounded bg-zinc-100 dark:bg-zinc-800">
                <span
                  className={`absolute inset-y-0 left-0 rounded ${
                    isCulprit || isZero ? "bg-rose-500" : "bg-primary/60"
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </span>
              <span
                className={`w-16 shrink-0 text-right tabular-nums ${
                  isZero
                    ? "font-semibold text-rose-600 dark:text-rose-400"
                    : "text-zinc-600 dark:text-zinc-400"
                }`}
              >
                {s.count.toLocaleString("pl-PL")}
              </span>
              <span className="w-14 shrink-0 text-rose-600 dark:text-rose-400">
                {isCulprit ? "← tutaj" : ""}
              </span>
            </li>
          );
        })}
      </ul>
      {diagnostics.first_zeroing_stage && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Poluzuj oznaczony filtr, aby zobaczyć kandydatów.
        </p>
      )}
    </div>
  );
}
