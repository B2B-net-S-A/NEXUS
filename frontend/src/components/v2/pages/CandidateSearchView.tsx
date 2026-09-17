"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  Bookmark,
  ChevronDown,
  ChevronUp,
  GitCompare,
  ListPlus,
  Loader2,
  Lock,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AiStatusBanner } from "@/components/jobs/AiStatusBanner";
import { FiltersPanel } from "@/components/v2/filters/FiltersPanel";
import { SEARCH_AVAILABILITY_OPTIONS } from "@/lib/search-availability";
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
import { JobShortlistPanel } from "@/components/v2/pages/JobShortlistPanel";
import { CandidateCompareModal } from "@/components/v2/pages/CandidateCompareModal";
import { shortlistApi } from "@/lib/candidate-search-api";
import { detectSavedSearchFormat } from "@/lib/saved-search-format";
import { parseTagInput } from "@/lib/parse-tag-input";
import {
  formatReasonCounts,
  summarizeBulkResult,
} from "@/lib/bulk-result-summary";
import {
  hasBreakdownDetail,
  summarizeBreakdown,
  unmeasuredReason,
  type MatchBreakdown,
} from "@/lib/match-breakdown";
import { assignErrorMessage } from "@/lib/assign-error";
import { eligibilityBadgeClass } from "@/lib/conflicts";
import { apiErrorMessage } from "@/lib/api-error";
import { encodeJobBackRef } from "@/lib/url-filters";
import {
  SEARCH_REQUEST_URL_PARAM,
  decodeSearchRequest,
  encodeSearchRequest,
  searchRequestValidationError,
} from "@/lib/candidate-search-request";
import {
  MATCH_SCORES_MAX_CANDIDATES,
  useVisibleMatchScores,
  type ScoreFailure,
} from "@/hooks/useVisibleMatchScores";

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
  // Runda 2 (2026-08-18): default "hybrid", nie "boolean". Bramka backendu
  // wymaga NIEPUSTEGO `q` (search.py: use_hybrid = mode=="hybrid" and q), więc
  // wyszukiwanie samymi filtrami zachowuje się identycznie jak dotąd — hybryda
  // (wektory + BM25 + rerank) włącza się dokładnie tam, gdzie wnosi wartość:
  // przy frazie tekstowej. Dotąd standalone /candidates/search nie dotykał
  // wektorów, dopóki użytkownik ręcznie nie kliknął „Semantycznie".
  search_mode: "hybrid",
};

// Wyniesione do `lib/parse-tag-input.ts` (współdzielone z `CreateJobModal`);
// re-eksport tutaj utrzymuje starą ścieżkę importu (`parseTagInput.test.ts`).
export { parseTagInput };

/** Ile osób obsługuje porównanie (`CandidateCompareModal`). */
export const COMPARE_MAX_CANDIDATES = 5;

/**
 * Po ilu ms od pustego wyniku odpalamy diagnostykę (wodospad kilku COUNT-ów).
 * Pauza w pisaniu dłuższa niż debounce (300 ms) daje pośredni zerowy wynik —
 * bez tej zwłoki każda taka pauza odpalała pełny wodospad.
 */
export const DIAGNOSTICS_DELAY_MS = 1000;

/**
 * Strona poza zakresem: odpowiedź bez wierszy przy `total > 0` na stronie > 1
 * (np. po dodaniu ostatnich osób ze strony do rekrutacji albo po `?s=` ze
 * starą stroną). Zwraca ostatnią istniejącą stronę albo `null`, gdy nie ma
 * czego poprawiać.
 */
export function clampedSearchPage(
  resp: Pick<CandidateSearchResponse, "items" | "total" | "page_size">,
  requestedPage: number,
): number | null {
  if (resp.items.length > 0 || resp.total <= 0 || requestedPage <= 1) return null;
  const lastPage = Math.max(1, Math.ceil(resp.total / Math.max(1, resp.page_size)));
  return lastPage < requestedPage ? lastPage : null;
}

/** Etykieta dostępności z tego samego słownika co filtr (bez surowego enuma). */
export function availabilityLabel(value: string): string {
  return (
    SEARCH_AVAILABILITY_OPTIONS.find((option) => option.value === value)?.label ??
    value.replace(/_/g, " ")
  );
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
  /** Preserve job-scoped search data while hiding every server mutation. */
  readOnly?: boolean;
  /**
   * Stan wyszukiwania (filtry, sortowanie, strona) w URL-u (`?s=`), żeby
   * Wstecz z profilu i odświeżenie wracały na to samo wyszukiwanie (UAT B29).
   * Tylko dla samodzielnej strony `/candidates/search` — w zakładce
   * rekrutacji URL należy do strony rekrutacji (`?tab=`).
   */
  syncUrl?: boolean;
}

/**
 * Standalone view for the manual CV search V2.
 *
 * Owns the request state, debounces user edits, and renders results below
 * the filter panel. The UI intentionally mirrors the structure of the AI
 * proposals tab so users moving between AI and manual search find the same
 * row layout (avatar, name, CC chip and skills).
 */
export function CandidateSearchView({
  initial,
  backHref,
  addToJob,
  onBulkAdded,
  readOnly = false,
  syncUrl = false,
}: CandidateSearchViewProps) {
  const searchParams = useSearchParams();
  // Baza = domyślne + kontekst rekrutacji + prefill; URL niesie tylko różnicę
  // względem niej. `initial` na stronie rekrutacji bywa nowym obiektem co
  // render, ale tam `syncUrl` jest wyłączone, więc efekt niżej nic nie robi.
  const baseRequest = useMemo<CandidateSearchRequest>(
    () => ({
      ...DEFAULT_REQUEST,
      ...(addToJob ? { exclude_in_job_id: addToJob.id } : {}),
      ...initial,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [addToJob?.id, initial],
  );
  // Stan z URL czytany PRZY MONTOWANIU (jak w CandidatesListV2): Wstecz
  // z profilu montuje stronę od nowa, więc inicjalizator wystarcza. Efekt na
  // wartości parametru ścigałby się z echem własnego `replaceState` niżej
  // (dwa szybkie wpisy → cofnięcie drugiego przez spóźnione echo pierwszego).
  const [request, setRequest] = useState<CandidateSearchRequest>(() =>
    syncUrl
      ? decodeSearchRequest(
          searchParams?.get(SEARCH_REQUEST_URL_PARAM) ?? null,
          baseRequest,
        )
      : baseRequest,
  );

  // URL ← stan: replaceState, żeby każda zmiana filtra nie dokładała wpisu
  // w historii (Wstecz ma prowadzić do poprzedniej strony, nie po filtrach).
  useEffect(() => {
    if (!syncUrl) return;
    const qs = encodeSearchRequest(request, baseRequest).toString();
    const { pathname } = window.location;
    window.history.replaceState(null, "", qs ? `${pathname}?${qs}` : pathname);
  }, [syncUrl, request, baseRequest]);
  const [data, setData] = useState<CandidateSearchResponse | null>(null);
  // Request, który wyprodukował `data` — diagnostyka pyta o TO zapytanie,
  // nie o to, które użytkownik właśnie pisze.
  const dataRequestRef = useRef<CandidateSearchRequest | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Błąd SAMEGO wyszukiwania ma własny stan: czyści wyniki i daje „Ponów".
  // Stare wyniki pod czerwonym paskiem czytały się jak aktualne.
  const [searchError, setSearchError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const [diagnostics, setDiagnostics] =
    useState<SearchDiagnosticsResponse | null>(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Imię i nazwisko zaznaczonych — zaznaczenie przeżywa zmianę strony, więc
  // porównanie nie może szukać ich w `data.items` bieżącej strony.
  const [selectedMeta, setSelectedMeta] = useState<
    Map<number, { id: number; name: string }>
  >(new Map());
  const queryClient = useQueryClient();
  const [bulkPending, setBulkPending] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkProposalsResponse | null>(null);
  const [bulkOptionsOpen, setBulkOptionsOpen] = useState(false);
  const [bulkNote, setBulkNote] = useState("");
  const [bulkTagsInput, setBulkTagsInput] = useState("");
  const [bulkStageId, setBulkStageId] = useState<number | "">("");
  const [assignableStages, setAssignableStages] = useState<AssignableStage[]>([]);
  const [shortlistPending, setShortlistPending] = useState(false);
  const [shortlistRefresh, setShortlistRefresh] = useState(0);
  const [compareOpen, setCompareOpen] = useState(false);

  // Saved searches — list refetched after every mutation.
  const [savedSearches, setSavedSearches] = useState<SavedSearchOut[]>([]);
  const [saveDraftOpen, setSaveDraftOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [savePinToJob, setSavePinToJob] = useState(true);
  const [savePending, setSavePending] = useState(false);
  const [reapprovalSearchId, setReapprovalSearchId] = useState<number | null>(
    null,
  );
  const [reapprovalPending, setReapprovalPending] = useState(false);
  const [reapprovalError, setReapprovalError] = useState<string | null>(null);

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
    if (!addToJob || readOnly) return;
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
  }, [addToJob, readOnly]);

  const toggleSelect = (item: CandidateSearchItem) => {
    const { id } = item;
    const wasSelected = selected.has(id);
    setSelected((prev) => {
      const next = new Set(prev);
      if (wasSelected) next.delete(id);
      else next.add(id);
      return next;
    });
    setSelectedMeta((prev) => {
      const next = new Map(prev);
      if (wasSelected) next.delete(id);
      else next.set(id, { id, name: `${item.name} ${item.lastname}` });
      return next;
    });
  };

  const clearSelection = () => {
    setSelected(new Set());
    setSelectedMeta(new Map());
  };

  const loadSavedSearch = (ss: SavedSearchOut) => {
    if (ss.requires_reapproval) {
      if (readOnly) return;
      setError(null);
      setReapprovalError(null);
      setReapprovalSearchId(ss.id);
      return;
    }
    setReapprovalError(null);
    setReapprovalSearchId(null);
    // SEARCH-P0-05 containment: saved searches from the GLOBAL candidates list
    // use a different payload ({qs, api}); opening one here used to silently
    // apply EMPTY filters. Detect and route instead — never open defaults.
    const format = detectSavedSearchFormat(ss.filters);
    if (format !== "search_request") {
      setError(
        format === "candidates_list"
          ? `Zapis „${ss.name}" pochodzi z globalnej listy kandydatów — otwórz go na stronie Kandydaci.`
          : `Zapis „${ss.name}" ma nieobsługiwany format — nie został otwarty.`,
      );
      return;
    }
    setError(null);
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

  const approveAndLoadSavedSearch = async () => {
    if (readOnly) return;
    const savedSearch = savedSearches.find(
      (search) => search.id === reapprovalSearchId,
    );
    if (!savedSearch) {
      setReapprovalSearchId(null);
      return;
    }
    setReapprovalPending(true);
    setReapprovalError(null);
    try {
      const approved = await savedSearchesApi.update(savedSearch.id, {
        confirm_reapproval: true,
      });
      if (approved.requires_reapproval) {
        throw new Error("Backend nie potwierdził ponownej akceptacji zapisu.");
      }
      setSavedSearches((current) =>
        current.map((search) => (search.id === approved.id ? approved : search)),
      );
      setReapprovalSearchId(null);
      loadSavedSearch(approved);
    } catch (err) {
      setReapprovalError(
        err instanceof Error
          ? err.message
          : "Ponowne zatwierdzenie nie powiodło się",
      );
    } finally {
      setReapprovalPending(false);
    }
  };

  const saveCurrentSearch = async () => {
    if (readOnly) return;
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
      setError(apiErrorMessage(err, "Zapisanie nie powiodło się"));
    } finally {
      setSavePending(false);
    }
  };

  const deleteSavedSearch = async (id: number) => {
    if (readOnly) return;
    try {
      await savedSearchesApi.remove(id);
      if (reapprovalSearchId === id) {
        setReapprovalSearchId(null);
        setReapprovalError(null);
      }
      refreshSavedSearches();
    } catch (err) {
      setError(apiErrorMessage(err, "Usunięcie nie powiodło się"));
    }
  };

  // The job page caches its kanban via react-query (["kanban", id] with the
  // route param as a STRING). Adding candidates from search (bulk-add or
  // shortlist promote) must invalidate it, or the Pipeline tab keeps showing
  // stale counts until a full page reload.
  const invalidatePipeline = useCallback(() => {
    if (!addToJob) return;
    const id = String(addToJob.id);
    queryClient.invalidateQueries({ queryKey: ["kanban", id] });
    queryClient.invalidateQueries({ queryKey: ["pipeline-scores", id] });
  }, [addToJob, queryClient]);

  const submitBulk = async () => {
    if (readOnly || !addToJob || selected.size === 0) return;
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
        // Telemetry: no full-search run here, so the outcome stays unattributed.
        source: "manual_search",
      });
      setBulkResult(resp);
      clearSelection();
      setBulkNote("");
      setBulkTagsInput("");
      setBulkStageId("");
      setBulkOptionsOpen(false);
      // Re-run the search so newly added candidates drop out (excluded).
      setRequest((r) => ({ ...r }));
      invalidatePipeline();
      onBulkAdded?.(resp);
    } catch (err) {
      setError(assignErrorMessage(err));
    } finally {
      setBulkPending(false);
    }
  };

  const submitShortlist = async () => {
    if (readOnly || !addToJob || selected.size === 0) return;
    setShortlistPending(true);
    setError(null);
    try {
      await shortlistApi.add(addToJob.id, Array.from(selected));
      clearSelection();
      setShortlistRefresh((n) => n + 1);
    } catch (err) {
      setError(apiErrorMessage(err, "Dodanie do shortlisty nie powiodło się"));
    } finally {
      setShortlistPending(false);
    }
  };

  // Debounce search by 300ms — typing in the free-text input shouldn't fire
  // a roundtrip per keystroke. The page resets to 1 on any non-page edit.
  //
  // ``cancelled`` lives in the EFFECT scope (not inside setTimeout) so a
  // superseded, still-in-flight request can never overwrite newer results —
  // the previous effect's cleanup flips its own flag before the next runs.
  useEffect(() => {
    // Odwrócony przedział (min > max) to kryterium niemożliwe: backend
    // odpowiada 422, a lista „wyników" pod nim to osoby bez danych. Nie
    // wysyłamy zapytania — pokazujemy błąd i prosimy o poprawkę (UAT B28).
    const validationError = searchRequestValidationError(request);
    if (validationError) {
      setLoading(false);
      setData(null);
      setSearchError(null);
      setError(validationError);
      return;
    }
    let cancelled = false;
    // Przerwane zapytanie nie tylko nie nadpisze nowszych wyników (flaga
    // `cancelled`), ale przestaje też obciążać retrieval, gdy ktoś pisze dalej.
    const controller = new AbortController();
    const handle = setTimeout(() => {
      setLoading(true);
      setError(null);
      setSearchError(null);
      candidateSearchApi
        .search(request, controller.signal)
        .then((resp) => {
          if (cancelled) return;
          const clamped = clampedSearchPage(resp, request.page ?? 1);
          if (clamped !== null) {
            // Strona zniknęła (np. po dodaniu ostatnich osób do rekrutacji):
            // przechodzimy na ostatnią istniejącą zamiast „Brak wyników".
            setRequest((current) =>
              current === request ? { ...current, page: clamped } : current,
            );
            return;
          }
          dataRequestRef.current = request;
          setData(resp);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setData(null);
          setSearchError(apiErrorMessage(err, "Wyszukiwanie nie powiodło się"));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(handle);
      controller.abort();
    };
  }, [request, retryNonce]);

  // Exclusion waterfall — only when a COMPLETED search returned nothing (it runs
  // several cumulative COUNT queries, so never fire it on a non-empty result).
  // Keyed on `data`: fires once per empty result, using the request that
  // produced it.
  //
  // Odpalana dopiero po `DIAGNOSTICS_DELAY_MS` od pustego wyniku i tylko,
  // gdy request, który go dał, jest nadal bieżący — pośrednie zera w trakcie
  // pisania (pauza > debounce) nie uruchamiają już wodospadu.
  useEffect(() => {
    if (!data || data.total > 0 || dataRequestRef.current !== request) {
      setDiagnostics(null);
      setDiagLoading(false);
      return;
    }
    const producedBy = request;
    let cancelled = false;
    setDiagLoading(true);
    const handle = setTimeout(() => {
      candidateSearchApi
        .diagnostics(producedBy)
        .then((d) => {
          if (!cancelled) setDiagnostics(d);
        })
        .catch(() => {
          if (!cancelled) setDiagnostics(null);
        })
        .finally(() => {
          if (!cancelled) setDiagLoading(false);
        });
    }, DIAGNOSTICS_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(handle);
    };
  }, [data, request]);

  // How many results actually state a value for a chip that no longer excludes
  // blanks. Built from `meta.soft_match_counts`, which the backend only fills
  // when such a chip was sent — so this is null on an ordinary search.
  const softMatchSummary = useMemo(() => {
    const counts = data?.meta?.soft_match_counts;
    if (!counts || !data) return null;
    const total = data.total;
    const parts: string[] = [];
    if (typeof counts.experience === "number") {
      parts.push(`${counts.experience} z podanym stażem w tym przedziale`);
    }
    if (typeof counts.location === "number") {
      parts.push(`${counts.location} z podaną pasującą lokalizacją`);
    }
    if (parts.length === 0) return null;
    return `Wśród ${total} wyników: ${parts.join(", ")}.`;
  }, [data]);

  // Match scores (job context only): canonical fit — the number C2 screens
  // show — measured on demand for the rows on screen only, at most 20 per
  // request (`useVisibleMatchScores`). Until 09.2026 this read a legacy cache
  // nothing writes any more, so the column was silently empty. A failed
  // request is a marker on the row ("brak dostępu" / "nie policzono —
  // ponów"), never an empty cell that reads as "not scored yet".
  const {
    scores: matchScores,
    breakdowns: matchBreakdowns,
    failures: matchFailures,
    onRowVisible,
    retry: retryMatchScores,
  } = useVisibleMatchScores(addToJob?.id, data?.items);

  // Stable while the selection and the result set are: the compare modal
  // keys its request on these ids, so a new array per render must not look
  // like a new comparison.
  // Z mapy zaznaczonych, nie z bieżącej strony: zaznaczenie przeżywa
  // paginację, więc porównanie obejmuje osoby ze WSZYSTKICH stron. Powyżej
  // `COMPARE_MAX_CANDIDATES` przycisk jest zablokowany z podpisem, zamiast po
  // cichu ucinać listę.
  const compareCandidates = useMemo(
    () => Array.from(selectedMeta.values()),
    [selectedMeta],
  );
  const compareTooMany = selected.size > COMPARE_MAX_CANDIDATES;

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
  const savedSearchAwaitingReapproval =
    reapprovalSearchId === null
      ? null
      : savedSearches.find((search) => search.id === reapprovalSearchId) ?? null;

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
          <div className="text-sm text-muted-foreground tabular-nums">
            {data.total} {data.total === 1 ? "wynik" : "wyniki"} ·{" "}
            {data.meta.took_ms} ms
          </div>
        )}
      </header>

      {/* Filtry doświadczenia i lokalizacji nie wycinają już kandydatów, u
          których pole jest puste (NULL_POLICY po stronie backendu) — bo na tej
          bazie taki filtr selekcjonował po kompletności rubryki, nie po
          trafności: „2–6 lat” zwężało realnie trafną pulę 11 091 osób do 45,
          przy 1,2% wypełnienia kolumny. Skutek uboczny jest taki, że wynik
          skacze do tysięcy, a rekruter, który wpisał wąski przedział, ma pełne
          prawo uznać że filtr się zepsuł. Ten pasek to wprost prostuje. */}
      {softMatchSummary && (
        <div
          role="status"
          className="rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground"
        >
          {softMatchSummary} Reszta nie ma tych danych uzupełnionych —
          zostawiamy ich niżej w wynikach, zamiast ukrywać.
        </div>
      )}

      {/* Tryb semantyczny ocenia trafność, więc ogląda ograniczoną pulę
          najbliższych znaczeniowo osób — `total` jest wtedy sufitem tej puli,
          a nie liczbą pasujących w bazie. Bez tego zdania przełączenie
          „Semantycznie” na zapytaniu ogólnym zamienia „11 091 wyników” w „200”
          i czyta się jak utrata bazy. Mówimy też, czym to odkręcić. */}
      {data?.meta?.result_cap_reached && (
        <div
          role="status"
          className="rounded-lg border border-border bg-muted px-3 py-2 text-sm text-foreground"
        >
          Tryb semantyczny pokazuje <strong>najtrafniejsze {data.total}</strong>{" "}
          osób, a nie wszystkie pasujące — to sufit tego trybu, nie rozmiar bazy.
          Doprecyzuj zapytanie, albo wyłącz „Semantycznie”, żeby przeszukać całą
          bazę filtrami.
        </div>
      )}

      {data?.meta && data.meta.ai_status !== "ok" && (
        <AiStatusBanner status={data.meta.ai_status} />
      )}

      {/* Osobny sygnał od `ai_status`, bo odpowiada na inne pytanie.
          `ai_status` mówi o kondycji usługi i schodzi do `down` dopiero po
          TRZECH kolejnych awariach; `search_degraded` mówi o TYM requeście.
          Pojedyncze zdegradowane wyszukiwanie wyglądało więc dla rekrutera
          identycznie jak komplet wyników — brak kandydata nie do odróżnienia
          od jego nieistnienia. */}
      {data?.meta?.search_degraded && data.meta.ai_status === "ok" && (
        <div
          role="status"
          className="flex items-start gap-3 rounded-lg border border-warning/40 bg-warning-muted p-3 text-sm text-warning-muted-foreground"
        >
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <strong>Wyniki niepełne.</strong> To wyszukiwanie poszło bez warstwy
            semantycznej — widzisz tylko dopasowania z filtrów i pełnotekstowe.
            Kandydat pasujący znaczeniowo (inne słowa, ten sam sens) mógł się nie
            pokazać. Spróbuj ponownie za chwilę.
          </div>
        </div>
      )}

      <FiltersPanel value={request} onChange={setRequestPatch} ccCounts={ccCounts} />

      {addToJob && (
        <JobShortlistPanel
          jobId={addToJob.id}
          refreshSignal={shortlistRefresh}
          readOnly={readOnly}
          onPromoted={() => {
            // Promoted candidate is now in the pipeline → refresh results + kanban.
            setRequest((r) => ({ ...r }));
            invalidatePipeline();
          }}
        />
      )}

      {/* Saved searches strip */}
      {(savedSearches.length > 0 || (!readOnly && saveDraftOpen)) && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground font-medium">
            Zapisane:
          </span>
          {savedSearches.map((ss) => (
            <span
              key={ss.id}
              className="group inline-flex items-center gap-1 rounded-md border bg-card px-2 py-1"
            >
              <button
                type="button"
                onClick={() => loadSavedSearch(ss)}
                disabled={readOnly && ss.requires_reapproval}
                title={
                  readOnly && ss.requires_reapproval
                    ? "Ten zapis wymaga ponownego zatwierdzenia w trybie edycji"
                    : undefined
                }
                className="hover:text-primary"
              >
                {ss.name}
              </button>
              {ss.pinned_to_job_id !== null && (
                <Badge variant="neutral" className="h-4 px-1 text-[10px]">
                  pin
                </Badge>
              )}
              {ss.requires_reapproval && (
                <Badge
                  variant="warning"
                  className="h-4 px-1 text-[10px]"
                  title="Miesięczne kryteria stawki zostały usunięte bez konwersji. Sprawdź zapis przed ponownym włączeniem alertów."
                >
                  ponownie zatwierdź
                </Badge>
              )}
              {!readOnly ? (
                <button
                  type="button"
                  aria-label={`Usuń ${ss.name}`}
                  onClick={() => deleteSavedSearch(ss.id)}
                  className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              ) : null}
            </span>
          ))}
          {!readOnly && !saveDraftOpen ? (
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
          ) : !readOnly ? (
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
          ) : null}
        </div>
      )}
      {!readOnly && savedSearches.length === 0 && !saveDraftOpen && (
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
      {!readOnly && savedSearchAwaitingReapproval && (
        <div
          role="alert"
          className="flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning-muted p-3 text-sm text-warning-muted-foreground sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="flex items-start gap-2">
            <TriangleAlert
              className="mt-0.5 h-4 w-4 shrink-0"
              aria-hidden="true"
            />
            <p>
              Z zapisanej konfiguracji „{savedSearchAwaitingReapproval.name}”
              usunięto miesięczne kryteria stawki bez konwersji. Nie zastosujemy
              pozostałych filtrów, dopóki jawnie ich nie zatwierdzisz.
              {reapprovalError && (
                <span className="mt-1 block font-medium">
                  {reapprovalError}
                </span>
              )}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="min-h-11"
              onClick={() => {
                setReapprovalSearchId(null);
                setReapprovalError(null);
              }}
              disabled={reapprovalPending}
            >
              Anuluj
            </Button>
            <Button
              type="button"
              size="sm"
              className="min-h-11"
              onClick={() => void approveAndLoadSavedSearch()}
              disabled={reapprovalPending}
            >
              {reapprovalPending && (
                <Loader2
                  className="mr-1 h-4 w-4 animate-spin"
                  aria-hidden="true"
                />
              )}
              Zatwierdź i zastosuj
            </Button>
          </div>
        </div>
      )}

      {/* Sort + status row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Sortuj:</span>
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
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            Ładowanie…
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-md border border-destructive/30 bg-destructive-muted p-3 text-sm text-destructive-muted-foreground">
          {error}
        </div>
      )}

      {searchError && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-destructive/30 bg-destructive-muted p-3 text-sm text-destructive-muted-foreground"
        >
          <span>{searchError}</span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setRetryNonce((n) => n + 1)}
            disabled={loading}
          >
            <RotateCcw className="h-3 w-3" aria-hidden="true" />
            Ponów
          </Button>
        </div>
      )}

      {bulkResult &&
        (() => {
          const summary = summarizeBulkResult(bulkResult);
          return (
            <div className="space-y-1 rounded-md border border-success/30 bg-success-muted p-3 text-sm text-success-muted-foreground">
              <div>
                Dodano {summary.added} kandydatów do requestu „{addToJob?.title}
                ".
              </div>
              {summary.warnings.length > 0 && (
                <div className="text-warning-muted-foreground">
                  ⚠ Z ostrzeżeniem: {formatReasonCounts(summary.warnings)}.
                </div>
              )}
              {summary.skipped.length > 0 && (
                <div className="text-muted-foreground">
                  Pominięto {bulkResult.total_skipped}:{" "}
                  {formatReasonCounts(summary.skipped)}.
                </div>
              )}
            </div>
          );
        })()}

      {/* Result rows */}
      <ul className="divide-y rounded-lg border bg-card">
        {data?.items.length === 0 && !loading && (
          <li className="p-4">
            <ExclusionWaterfall
              diagnostics={diagnostics}
              loading={diagLoading}
            />
          </li>
        )}
        {data?.items.map((c, index) => (
          <CandidateSearchRow
            key={c.id}
            item={c}
            selectable={Boolean(addToJob)}
            selected={selected.has(c.id)}
            onToggleSelect={() => toggleSelect(c)}
            backRefJobId={addToJob?.id}
            score={matchScores[String(c.id)]}
            breakdown={matchBreakdowns[String(c.id)]}
            scoreFailure={matchFailures[String(c.id)]}
            onRetryScore={retryMatchScores}
            onVisible={addToJob ? onRowVisible : undefined}
            scoreWithoutObserver={index < MATCH_SCORES_MAX_CANDIDATES}
          />
        ))}
      </ul>

      {/* Sticky bulk-add bar — only when in job context */}
      {addToJob && selected.size > 0 && (
        <div className="sticky bottom-4 z-10 mx-auto flex w-fit max-w-full flex-col items-center gap-2">
          {!readOnly && bulkOptionsOpen && (
            <div className="w-80 max-w-full space-y-2 rounded-xl border bg-card p-3 text-left shadow-lg">
              {assignableStages.length > 0 && (
                <div className="space-y-1">
                  <label
                    htmlFor="bulk-stage"
                    className="text-xs font-medium text-muted-foreground"
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
                    className="w-full rounded-md border bg-background px-2 py-1.5 text-xs focus:outline-hidden focus:ring-1 focus:ring-ring"
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
                  className="text-xs font-medium text-muted-foreground"
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
                  className="w-full resize-none rounded-md border bg-background px-2 py-1.5 text-xs focus:outline-hidden focus:ring-1 focus:ring-ring"
                />
              </div>
              <div className="space-y-1">
                <label
                  htmlFor="bulk-tags"
                  className="text-xs font-medium text-muted-foreground"
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
          <div className="flex w-fit items-center gap-3 rounded-full border bg-foreground px-4 py-2 text-sm text-background shadow-lg">
            <span className="tabular-nums">
              Wybrano <strong>{selected.size}</strong>
            </span>
            {!readOnly ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 gap-1 text-xs text-background hover:bg-background/15 hover:text-background"
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
            ) : null}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 text-xs text-background hover:bg-background/15 hover:text-background"
              onClick={clearSelection}
              disabled={bulkPending || shortlistPending}
            >
              Wyczyść
            </Button>
            {!readOnly ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 gap-1 text-xs text-background hover:bg-background/15 hover:text-background"
                onClick={submitShortlist}
                disabled={bulkPending || shortlistPending}
              >
                {shortlistPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <ListPlus className="h-3 w-3" />
                )}
                Do shortlisty
              </Button>
            ) : null}
            {selected.size >= 2 && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-7 gap-1 text-xs text-background hover:bg-background/15 hover:text-background"
                onClick={() => {
                  if (!compareTooMany) setCompareOpen(true);
                }}
                disabled={bulkPending || shortlistPending || compareTooMany}
                title={
                  compareTooMany
                    ? `Porównanie obsługuje do ${COMPARE_MAX_CANDIDATES} osób`
                    : undefined
                }
              >
                <GitCompare className="h-3 w-3" />
                {compareTooMany
                  ? `Porównaj (maks. ${COMPARE_MAX_CANDIDATES})`
                  : "Porównaj"}
              </Button>
            )}
            {!readOnly ? (
              <Button
                type="button"
                size="sm"
                className="h-7 gap-1 bg-primary text-primary-foreground hover:bg-primary/90"
                onClick={submitBulk}
                disabled={bulkPending || shortlistPending}
              >
                {bulkPending ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <Plus className="h-3 w-3" />
                )}
                Dodaj do „{addToJob.title}"
              </Button>
            ) : null}
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
          <span className="text-muted-foreground tabular-nums">
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

      {compareOpen && addToJob && !compareTooMany && (
        <CandidateCompareModal
          jobId={addToJob.id}
          candidates={compareCandidates}
          onClose={() => setCompareOpen(false)}
        />
      )}
    </div>
  );
}

interface CandidateSearchRowProps {
  item: CandidateSearchItem;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: () => void;
  /** Canonical fit (0-100) vs. the job — the number C2 screens show. */
  score?: number;
  /** Fit breakdown (per-layer points + matched/gap skills, or why unmeasured). */
  breakdown?: MatchBreakdown;
  /** The score request for this row failed (403 / anything else). */
  scoreFailure?: ScoreFailure;
  /** Ask again for the rows whose score request failed. */
  onRetryScore?: () => void;
  /** Reports the row once it is on screen, so only visible rows get scored. */
  onVisible?: (candidateId: number) => void;
  /**
   * Without IntersectionObserver (SSR, very old browsers) nothing is "on
   * screen"; only the first `MATCH_SCORES_MAX_CANDIDATES` rows then ask.
   */
  scoreWithoutObserver?: boolean;
  /**
   * Rekrutacja, z której otwarto wyszukiwanie: link do profilu niesie
   * `from=job&jobId=`, żeby „Wróć" prowadziło do rekrutacji, nie do listy.
   */
  backRefJobId?: number;
}

/** Calls `onVisible(id)` the first time the element enters the viewport. */
function useReportWhenVisible(
  ref: RefObject<HTMLElement | null>,
  id: number,
  onVisible: ((candidateId: number) => void) | undefined,
  fallback: boolean,
) {
  useEffect(() => {
    if (!onVisible) return;
    const element = ref.current;
    if (!element) return;
    if (typeof IntersectionObserver === "undefined") {
      if (fallback) onVisible(id);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        observer.disconnect();
        onVisible(id);
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
    // `onVisible` changes identity per result set, re-arming the observer.
  }, [ref, id, onVisible, fallback]);
}

export function scoreBadgeClass(score: number): string {
  if (score >= 70)
    return "bg-success-muted text-success-muted-foreground";
  if (score >= 40)
    return "bg-warning-muted text-warning-muted-foreground";
  return "bg-muted text-muted-foreground";
}

function CandidateSearchRow({
  item,
  selectable = false,
  selected = false,
  onToggleSelect,
  score,
  breakdown,
  scoreFailure,
  onRetryScore,
  onVisible,
  scoreWithoutObserver = false,
  backRefJobId,
}: CandidateSearchRowProps) {
  const rowRef = useRef<HTMLLIElement>(null);
  useReportWhenVisible(rowRef, item.id, onVisible, scoreWithoutObserver);
  const [showBreakdown, setShowBreakdown] = useState(false);
  const canExpand = typeof score === "number" && hasBreakdownDetail(breakdown);
  const failure = typeof score !== "number" ? scoreFailure : undefined;
  const notMeasured =
    typeof score !== "number" && !failure
      ? unmeasuredReason(breakdown?.measurement)
      : null;
  const skillsList = Array.isArray(item.skills)
    ? (item.skills as Array<string | { name?: string }>)
    : [];
  const skillNames = skillsList
    .map((s) => (typeof s === "string" ? s : s.name ?? null))
    .filter((s): s is string => Boolean(s))
    .slice(0, 6);
  const formattedLocation = formatCandidateLocation(item.location);
  // `eligibility` przychodzi tylko w kontekście rekrutacji (`exclude_in_job_id`).
  // Konflikt z klientem (czarna lista klienta / NDA / konkurent) od 17.09.2026
  // jest ostrzeżeniem; zaznaczyć NIE da się wyłącznie przy wecie HM.
  const eligibility = item.eligibility ?? null;
  const assignBlocked = eligibility?.assignment_allowed === false;

  return (
    <li ref={rowRef} className="p-3 hover:bg-muted/50">
      <div className="flex items-start gap-3">
      {selectable && (
        <input
          type="checkbox"
          checked={selected && !assignBlocked}
          onChange={onToggleSelect}
          disabled={assignBlocked}
          title={assignBlocked ? eligibility?.reason : undefined}
          aria-label={`Zaznacz ${item.name} ${item.lastname}`}
          className="mt-1 h-4 w-4 rounded border-input text-primary focus:ring-ring disabled:cursor-not-allowed disabled:opacity-40"
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
              : "Dopasowanie do requestu (0-100, ten sam wynik co w dopasowaniu AI)"
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
      {failure === "forbidden" && (
        <span
          role="img"
          aria-label="Brak dostępu do oceny dopasowania"
          title="Brak dostępu do oceny dopasowania dla tej rekrutacji"
          className="mt-0.5 inline-flex h-6 w-9 shrink-0 cursor-help items-center justify-center rounded-md border border-dashed border-border text-muted-foreground"
        >
          <Lock className="h-3 w-3" aria-hidden="true" />
        </span>
      )}
      {failure === "retry" && (
        <button
          type="button"
          onClick={onRetryScore}
          aria-label="Nie policzono dopasowania — ponów"
          title="Nie policzono dopasowania — kliknij, aby ponowić"
          className="mt-0.5 inline-flex h-6 w-9 shrink-0 items-center justify-center rounded-md bg-warning-muted text-warning-muted-foreground hover:ring-1 hover:ring-ring"
        >
          <RotateCcw className="h-3 w-3" aria-hidden="true" />
        </button>
      )}
      {notMeasured && (
        <span
          role="img"
          aria-label={`Ocena niepełna: ${notMeasured}`}
          title={`Ocena niepełna: ${notMeasured}`}
          className="mt-0.5 inline-flex h-6 w-9 shrink-0 cursor-help items-center justify-center rounded-md bg-muted text-xs font-semibold text-muted-foreground"
        >
          —
        </span>
      )}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <Link
            href={
              backRefJobId
                ? `/candidates/${item.id}?${encodeJobBackRef(backRefJobId)}`
                : `/candidates/${item.id}`
            }
            className="font-medium hover:underline"
          >
            {item.name} {item.lastname}
          </Link>
          {item.competence_category && (
            <Badge variant="neutral">{item.competence_category}</Badge>
          )}
          {item.is_champion && (
            <Badge className="bg-warning-muted text-warning-muted-foreground">
              Champion
            </Badge>
          )}
          {eligibility && (
            <span
              className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-medium ${eligibilityBadgeClass(eligibility)}`}
              title={eligibility.reason}
              data-testid={`search-eligibility-${item.id}`}
            >
              <AlertCircle className="h-3 w-3 shrink-0" aria-hidden="true" />
              {eligibility.reason}
            </span>
          )}
          {item.years_it_experience !== null && (
            <span className="text-xs text-muted-foreground">
              {item.years_it_experience} lat IT
            </span>
          )}
          {formattedLocation && (
            <span className="text-xs text-muted-foreground">
              {formattedLocation}
            </span>
          )}
        </div>
        {skillNames.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {skillNames.map((s) => (
              <span
                key={s}
                className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground"
              >
                {s}
              </span>
            ))}
          </div>
        )}
        {item.ai_summary && (
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {item.ai_summary}
          </p>
        )}
      </div>
      <div className="text-right text-xs text-muted-foreground tabular-nums whitespace-nowrap">
        {item.availability_status && (
          <div>{availabilityLabel(item.availability_status)}</div>
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
              ? "bg-success-muted text-success-muted-foreground"
              : "bg-destructive-muted text-destructive-muted-foreground"
          }`}
        >
          {t}
        </span>
      ))}
    </>
  );
  return (
    <div className="ml-12 mt-2 space-y-2 rounded-lg border bg-muted/40 p-3">
      {s.layers.length > 0 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {s.layers.map((l) => (
            <span key={l.key} className="tabular-nums">
              {l.label}{" "}
              {l.status === "not_comparable" ? (
                <strong title={l.reason}>nieporównywalne</strong>
              ) : l.status === "unknown" ? (
                <strong title={l.reason}>brak danych</strong>
              ) : (
                <strong>
                  {l.points}/{l.max}
                </strong>
              )}
            </span>
          ))}
        </div>
      )}
      {(s.matchedMust.length > 0 || s.gapMust.length > 0) && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-1 text-xs font-medium text-muted-foreground">
            Wymagane:
          </span>
          <Chips items={s.matchedMust} tone="ok" />
          <Chips items={s.gapMust} tone="gap" />
        </div>
      )}
      {(s.matchedNice.length > 0 || s.gapNice.length > 0) && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="mr-1 text-xs font-medium text-muted-foreground">
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
      <div className="flex items-center justify-center gap-2 py-2 text-sm text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Analizuję, który filtr zawęził wyniki…
      </div>
    );
  }
  if (!diagnostics || diagnostics.stages.length === 0) {
    return (
      <div className="py-2 text-center text-sm text-muted-foreground">
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
                  i === 0 ? "font-medium" : "text-muted-foreground"
                }`}
              >
                {s.label}
              </span>
              <span className="relative h-4 flex-1 overflow-hidden rounded bg-muted">
                <span
                  className={`absolute inset-y-0 left-0 rounded ${
                    isCulprit || isZero ? "bg-destructive" : "bg-primary/60"
                  }`}
                  style={{ width: `${pct}%` }}
                />
              </span>
              <span
                className={`w-16 shrink-0 text-right tabular-nums ${
                  isZero
                    ? "font-semibold text-destructive"
                    : "text-muted-foreground"
                }`}
              >
                {s.count.toLocaleString("pl-PL")}
              </span>
              <span className="w-14 shrink-0 text-destructive">
                {isCulprit ? "← tutaj" : ""}
              </span>
            </li>
          );
        })}
      </ul>
      {diagnostics.first_zeroing_stage && (
        <p className="text-xs text-muted-foreground">
          Poluzuj oznaczony filtr, aby zobaczyć kandydatów.
        </p>
      )}
    </div>
  );
}
