"use client";

/**
 * Dane segmentu „Propozycje z bazy": skrzynka propozycji + żywy przegląd bazy
 * + podobne projekty + rekomendacje, scalone w jedną listę (`proposals-merge`).
 *
 * Przegląd bazy działa DOKŁADNIE jak w dawnej zakładce AI Matching: start
 * wyłącznie jawnym kliknięciem, ten sam klucz w localStorage
 * (`nexus-full-job:{user}:{job}`), więc Talent Radar „Zapisana rekrutacja"
 * i ten widok pokazują ten sam przegląd.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { useFullCandidateSearch } from "@/hooks/useFullCandidateSearch";
import {
  historicalCandidatesApi,
  matchingApi,
  proposalsApi,
  type ProposalSnapshot,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { assignErrorMessage } from "@/lib/assign-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import {
  proposalsBulkApi,
  shortlistApi,
  type BulkAddSource,
  type BulkProposalsRequest,
  type BulkProposalsResponse,
} from "@/lib/candidate-search-api";
import { searchFailed, searchIsRunning } from "@/lib/full-candidate-search-api";
import { summarizeFullSearch } from "@/lib/full-search-summary";
import {
  jobProposalsApi,
  jobProposalsKeys,
  type ProposalInboxPage,
} from "@/lib/job-proposals-api";
import {
  countBySource,
  filterProposals,
  mergeProposals,
  type ProposalEntry,
  type ProposalViewFilters,
} from "@/lib/proposals-merge";
import { httpStatusFromError } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";
import { jobShortlistQueryKey } from "@/components/v2/jobs/JobShortlist";

import type { ProposalSource } from "./types";

const INBOX_PAGE = 50;

export interface UseJobProposalsOptions {
  filters: ProposalViewFilters;
  budgetHourly: number | null;
  /**
   * Osoby już w rekrutacji (z kanbana rodzica). Brak = hook sam pyta
   * `pipeline-scores` — tym samym kluczem co dawna zakładka AI Matching.
   */
  pipelineCandidateIds?: readonly number[];
  readOnly?: boolean;
  /** Podobne projekty i rekomendacje — leniwie, dopiero gdy segment jest otwarty. */
  secondarySourcesEnabled?: boolean;
}

export interface AddToJobOptions {
  stageDefId?: number | null;
  note?: string | null;
  tags?: string[];
}

interface AddGroup {
  ids: number[];
  source: BulkAddSource | null;
  runId: string | null;
}

/**
 * Telemetria dopasowań: `source` i `run_id` wynikają z POCHODZENIA wiersza,
 * nigdy z domysłu. Pierwszeństwo: żywy przegląd użytkownika → skrzynka
 * propozycji (z `run_id` przeglądu, który tę osobę zaproponował, jeśli serwer
 * go podał) → podobne projekty → rekomendacje. Backend i tak przypina wynik do
 * przeglądu tylko wtedy, gdy ten naprawdę pokazał kandydata.
 */
export function groupAddsByOrigin(entries: readonly ProposalEntry[]): AddGroup[] {
  const groups = new Map<string, AddGroup>();
  for (const { row, detail } of entries) {
    const origins = detail.origins;
    const group: Omit<AddGroup, "ids"> =
      origins.includes("run") && row.runId
        ? { source: "full_search", runId: row.runId }
        : origins.includes("inbox")
          ? { source: "proposal_inbox", runId: row.runId }
          : origins.includes("similar")
            ? { source: "historical", runId: null }
            : origins.includes("recommendation")
              ? { source: "recommendation", runId: null }
              : { source: null, runId: null };
    const key = `${group.source}:${group.runId}`;
    const existing = groups.get(key);
    if (existing) existing.ids.push(row.candidateId);
    else groups.set(key, { ...group, ids: [row.candidateId] });
  }
  return Array.from(groups.values());
}

/** Źródło dla „Pomiń" osoby, której skrzynka jeszcze nie zna. */
export function dismissSourceFor(entry: ProposalEntry | undefined): ProposalSource {
  return entry?.row.sources[0] ?? "full_base";
}

function mergeBulkResponses(parts: BulkProposalsResponse[]): BulkProposalsResponse {
  return parts.reduce<BulkProposalsResponse>(
    (acc, part) => ({
      added: [...acc.added, ...part.added],
      skipped: [...acc.skipped, ...part.skipped],
      warnings: [...(acc.warnings ?? []), ...(part.warnings ?? [])],
      total_added: acc.total_added + part.total_added,
      total_skipped: acc.total_skipped + part.total_skipped,
    }),
    { added: [], skipped: [], warnings: [], total_added: 0, total_skipped: 0 },
  );
}

export function useJobProposals(jobId: number, options: UseJobProposalsOptions) {
  const {
    filters,
    budgetHourly,
    pipelineCandidateIds,
    readOnly = false,
    secondarySourcesEnabled = true,
  } = options;
  const queryClient = useQueryClient();
  const { showSuccess, showError, showToast, showActionToast } = useToast();
  const actorId = useAuthStore((s) => s.user?.id);

  // ── Żywy przegląd bazy (jak AI Matching) ─────────────────────────────────
  const fullSearch = useFullCandidateSearch({
    includeCandidateDetails: true,
    shareAcrossTabs: true,
    storageKey: actorId ? `nexus-full-job:${actorId}:${jobId}` : undefined,
    // `stage: "out"` — propozycje to z definicji osoby SPOZA rekrutacji;
    // serwer filtruje zapisane wyniki przed stronicowaniem, nie skanuje od nowa.
    filters: {
      skill: filters.skill ?? undefined,
      // Chip „W budżecie" NIE idzie do serwera jako `rate: "in"` — tamten
      // filtr odsiewa też stawki nieznane, a chip ma je przepuszczać
      // (odsiewa `filterProposals` po stronie widoku).
      rate: filters.rate,
      stage: "out",
      location: filters.location.trim(),
    },
  });
  const { setMinScore } = fullSearch;
  useEffect(() => {
    setMinScore(filters.minScore);
  }, [filters.minScore, setMinScore]);

  // Klaster KPI w nagłówku („w rankingu", „≥ N pkt") czyta ten klucz WYŁĄCZNIE
  // z cache'u — publikuje go ten, kto ma żywy przegląd (dawniej: AI Matching).
  const runSummary = useMemo(
    () => summarizeFullSearch(fullSearch.data, Boolean(fullSearch.error)),
    [fullSearch.data, fullSearch.error],
  );
  useEffect(() => {
    queryClient.setQueryData(["full-search-summary", actorId, jobId], runSummary);
  }, [queryClient, actorId, jobId, runSummary]);

  const startRun = useCallback(() => {
    if (readOnly) return;
    void fullSearch.start({ job_id: jobId });
  }, [fullSearch, jobId, readOnly]);
  // „Spróbuj ponownie" czyta bieżący przegląd; nowy skan tylko wtedy, gdy
  // zapisanego nie da się już odczytać (przerwany, wygasł, zmienił się request).
  const retryRun = useCallback(() => {
    if (fullSearch.runId && !fullSearch.needsNewRun) void fullSearch.refresh();
    else startRun();
  }, [fullSearch, startRun]);

  // ── Skrzynka propozycji ──────────────────────────────────────────────────
  const inboxKey = jobProposalsKeys.inbox(jobId, INBOX_PAGE);
  const inbox = useInfiniteQuery({
    queryKey: inboxKey,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      jobProposalsApi.inbox(jobId, { status: "proposed", limit: INBOX_PAGE, offset: pageParam }, signal),
    getNextPageParam: (last) => last.next_offset ?? undefined,
    staleTime: 30_000,
  });
  const inboxItems = useMemo(
    () => inbox.data?.pages.flatMap((p) => p.items) ?? [],
    [inbox.data],
  );
  const inboxTotal = inbox.data?.pages[0]?.total ?? 0;
  const inboxHidden = inbox.data?.pages.reduce((n, p) => n + p.hidden_on_page, 0) ?? 0;

  const latestRun = useQuery({
    queryKey: jobProposalsKeys.latestRun(jobId),
    queryFn: ({ signal }) => jobProposalsApi.latestRun(jobId, signal),
    staleTime: 60_000,
  });

  // Przeglądarka nie zna żadnego przeglądu → podpinamy ostatni zakończony
  // z serwera (własny albo nocny automat — tylko takie zwraca `latest-run`).
  const { adopt: adoptRun, runId: currentRunId, starting: runStarting } = fullSearch;
  const latestRunId = latestRun.data?.run?.run_id ?? null;
  useEffect(() => {
    if (latestRunId && currentRunId === null && !runStarting) adoptRun(latestRunId);
  }, [latestRunId, currentRunId, runStarting, adoptRun]);

  // ── Źródła dodatkowe (klucze wspólne z dotychczasowymi sekcjami) ─────────
  const similar = useQuery({
    queryKey: jobProposalsKeys.similar(jobId),
    enabled: secondarySourcesEnabled,
    queryFn: async () =>
      (await historicalCandidatesApi.forJob(jobId, { tier: "primary", limit: 20, include_negative: true })).data,
    staleTime: 60_000,
  });
  const recommendations = useQuery<ProposalSnapshot | null>({
    queryKey: jobProposalsKeys.recommendations(jobId),
    enabled: secondarySourcesEnabled,
    queryFn: async () => {
      try {
        return (await proposalsApi.latest(jobId)).data;
      } catch (error) {
        // 404 = rekrutacja nie ma jeszcze migawki rekomendacji — to nie awaria.
        if (httpStatusFromError(error) === 404) return null;
        throw error;
      }
    },
    refetchInterval: (query) => (query.state.data?.status === "pending" ? 3000 : false),
    staleTime: 60_000,
  });
  const regenerate = useMutation({
    mutationFn: () => proposalsApi.regenerate(jobId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.recommendations(jobId) });
      showSuccess("Odświeżamy rekomendacje — pojawią się za chwilę.");
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się odświeżyć rekomendacji.")),
  });

  const ownPipeline = useQuery({
    queryKey: ["pipeline-scores", jobId],
    enabled: pipelineCandidateIds === undefined,
    queryFn: () => matchingApi.pipelineScores(jobId).then((r) => r.data),
    staleTime: 60_000,
  });
  const pipelineIds = pipelineCandidateIds ?? ownPipeline.data?.pipeline_candidate_ids;

  // Dodani/pominięci znikają od razu — odświeżenie źródeł dogania w tle.
  const [hiddenIds, setHiddenIds] = useState<ReadonlySet<number>>(new Set());
  useEffect(() => setHiddenIds(new Set()), [jobId]);

  const runData = fullSearch.data;
  const runUsable =
    runData !== undefined && !searchIsRunning(runData.state) && !searchFailed(runData.state) && !fullSearch.needsNewRun;
  const allEntries = useMemo(
    () =>
      mergeProposals({
        inbox: inboxItems,
        run: runUsable && runData ? { runId: runData.run_id, rows: runData.results } : null,
        similar: similar.data?.candidates,
        recommendations:
          recommendations.data?.status === "ready"
            ? { items: recommendations.data.candidates, degraded: recommendations.data.degraded }
            : null,
        pipelineCandidateIds: pipelineIds,
        budgetHourly,
      }).filter((e) => !hiddenIds.has(e.row.candidateId)),
    [inboxItems, runUsable, runData, similar.data, recommendations.data, pipelineIds, budgetHourly, hiddenIds],
  );
  // Liczniki pigułek źródeł ignorują sam filtr źródła — inaczej kliknięcie
  // jednej pigułki zerowałoby pozostałe.
  const sourceCounts = useMemo(
    () => countBySource(filterProposals(allEntries, { ...filters, source: "all" }, { budgetHourly })),
    [allEntries, filters, budgetHourly],
  );
  // Pasek etapów pokazuje łączną liczbę ze wszystkich źródeł, nie samą skrzynkę.
  const totalProposals = sourceCounts.all;
  useEffect(() => {
    if (totalProposals != null) queryClient.setQueryData(jobProposalsKeys.visibleCount(jobId), totalProposals);
  }, [queryClient, jobId, totalProposals]);
  const entries = useMemo(
    () => filterProposals(allEntries, filters, { budgetHourly }),
    [allEntries, filters, budgetHourly],
  );
  const rows = useMemo(() => entries.map((e) => e.row), [entries]);
  const entryById = useMemo(
    () => new Map(allEntries.map((e) => [e.row.candidateId, e])),
    [allEntries],
  );

  // „Awaria silnika", nie „ktoś nie ma wektora": nic z widocznej strony
  // ŻYWEGO przeglądu nie zostało zmierzone albo podobne projekty zgłaszają
  // degradację. Zdegradowana MIGAWKA rekomendacji czerwonego banera nie
  // zapala — jest zapisem z przeszłości (bywa sprzed tygodni), a nie stanem
  // silnika teraz; dostaje własną, małą notkę przy liście.
  const runUnmeasured =
    runUsable && !!runData && runData.results.length > 0 && runData.results.every((r) => r.measurement === "unavailable");
  const engineDegraded = runUnmeasured || similar.data?.tier_used === "degraded";

  const invalidateAfterAdd = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
    void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
    void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
    // Licznik propozycji na liście rekrutacji jest wspólny dla zespołu.
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
  }, [queryClient, jobId]);

  const addMutation = useMutation({
    mutationFn: async ({ candidateIds, opts }: { candidateIds: number[]; opts: AddToJobOptions }) => {
      if (readOnly) throw new Error("Sekcja Pipeline jest dostępna tylko do odczytu.");
      const picked = candidateIds.flatMap((id) => entryById.get(id) ?? []);
      const parts: BulkProposalsResponse[] = [];
      for (const group of groupAddsByOrigin(picked)) {
        const body: BulkProposalsRequest = { candidate_ids: group.ids };
        if (opts.stageDefId != null) body.initial_stage_def_id = opts.stageDefId;
        if (opts.note) body.note = opts.note;
        if (opts.tags?.length) body.tags = opts.tags;
        if (group.source) body.source = group.source;
        if (group.runId) body.run_id = group.runId;
        parts.push(await proposalsBulkApi.add(jobId, body));
      }
      return mergeBulkResponses(parts);
    },
    onSuccess: (response, { candidateIds }) => {
      // Znikają dodani ORAZ „już w rekrutacji"; pozostałe odmowy (weto HM,
      // czarna lista) zostają na liście z powodem w komunikacie.
      const gone = new Set<number>(response.added);
      response.skipped.filter((s) => s.reason === "already_in_job").forEach((s) => gone.add(s.candidate_id));
      setHiddenIds((prev) => new Set([...prev, ...candidateIds.filter((id) => gone.has(id))]));
      invalidateAfterAdd();
      const summary = summarizeBulkResult(response);
      const tail = [
        summary.skipped.length ? `pominięto: ${formatReasonCounts(summary.skipped)}` : "",
        summary.warnings.length ? `uwaga: ${formatReasonCounts(summary.warnings)}` : "",
      ].filter(Boolean).join("; ");
      const head = summary.added > 0 ? `Dodano do rekrutacji: ${summary.added}` : "Nikogo nie dodano";
      showToast(tail ? `${head} — ${tail}` : head, summary.added > 0 ? "success" : "error");
    },
    onError: (error) => showError(assignErrorMessage(error)),
  });

  const restoreMutation = useMutation({
    mutationFn: async (candidateIds: number[]) => {
      for (const id of candidateIds) await jobProposalsApi.restore(jobId, id);
    },
    onSuccess: (_data, ids) => {
      const back = new Set(ids);
      setHiddenIds((prev) => new Set([...prev].filter((id) => !back.has(id))));
      showSuccess(ids.length === 1 ? "Przywrócono propozycję." : `Przywrócono propozycje: ${ids.length}.`);
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się cofnąć pominięcia.")),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
    },
  });
  const { mutate: restoreMutate } = restoreMutation;

  const dismissMutation = useMutation({
    mutationFn: async (candidateIds: number[]) => {
      if (readOnly) throw new Error("Sekcja Pipeline jest dostępna tylko do odczytu.");
      // „Pomiń" jest TRWAŁE dla każdej osoby — także spoza skrzynki (żywy
      // przegląd, podobne projekty, rekomendacje): serwer zakłada wtedy wiersz
      // od razu jako pominięty. Zwraca tych, których naprawdę pominięto.
      const dismissed: number[] = [];
      for (const id of candidateIds) {
        try {
          await jobProposalsApi.dismiss(jobId, id, dismissSourceFor(entryById.get(id)));
          dismissed.push(id);
        } catch (error) {
          // 404 = kandydat zniknął; 409 = ktoś z zespołu właśnie dodał tę osobę
          // do rekrutacji. W obu przypadkach wiersz i tak ma zniknąć z listy.
          const status = httpStatusFromError(error);
          if (status !== 404 && status !== 409) throw error;
        }
      }
      return dismissed;
    },
    onMutate: async (candidateIds) => {
      await queryClient.cancelQueries({ queryKey: inboxKey });
      const previousInbox = queryClient.getQueryData<InfiniteData<ProposalInboxPage>>(inboxKey);
      const previousHidden = hiddenIds;
      const drop = new Set(candidateIds);
      setHiddenIds((prev) => new Set([...prev, ...candidateIds]));
      if (previousInbox) {
        queryClient.setQueryData<InfiniteData<ProposalInboxPage>>(inboxKey, {
          ...previousInbox,
          pages: previousInbox.pages.map((p) => ({ ...p, items: p.items.filter((i) => !drop.has(i.candidate.id)) })),
        });
      }
      return { previousInbox, previousHidden };
    },
    onError: (error, _ids, context) => {
      if (context?.previousInbox) queryClient.setQueryData(inboxKey, context.previousInbox);
      if (context) setHiddenIds(context.previousHidden);
      showError(apiErrorMessage(error, "Nie udało się pominąć propozycji."));
    },
    onSuccess: (dismissed, ids) => {
      const message =
        ids.length === 1 ? "Pominięto — wróci tylko z nową wersją CV." : `Pominięto: ${ids.length}. Wrócą tylko z nową wersją CV.`;
      if (dismissed.length === 0) {
        showSuccess(message);
        return;
      }
      // Pomyłka o jeden wiersz jest tu najczęstszym błędem (skrót „P").
      showActionToast(message, { actionLabel: "Cofnij", onAction: () => restoreMutate(dismissed) });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
    },
  });

  const shortlistMutation = useMutation({
    mutationFn: (candidateIds: number[]) => {
      if (readOnly) throw new Error("Shortlista jest dostępna tylko do odczytu.");
      return shortlistApi.add(jobId, candidateIds);
    },
    onSuccess: (response) => {
      void queryClient.invalidateQueries({ queryKey: jobShortlistQueryKey(jobId) });
      showSuccess(response.total_added > 0 ? `Dodano na shortlistę: ${response.total_added}` : "Zaznaczeni są już na shortliście");
    },
    onError: (error) => showError(assignErrorMessage(error)),
  });

  const { mutate: addMutate } = addMutation;
  const { mutate: dismissMutate } = dismissMutation;
  const { mutate: shortlistMutate } = shortlistMutation;

  return {
    rows,
    entries,
    entryById,
    /** Przed filtrami widoku — rozróżnia „nic nie ma" od „filtry wszystko ukryły". */
    totalBeforeFilters: allEntries.length,
    sourceCounts,
    status: {
      run: fullSearch,
      startRun,
      retryRun,
      latestRun: latestRun.data?.run ?? null,
      engineDegraded,
      inbox: {
        total: inboxTotal,
        hidden: inboxHidden,
        isSuccess: inbox.isSuccess,
        isLoading: inbox.isPending,
        isError: inbox.isError,
        error: inbox.error,
        hasMore: inbox.hasNextPage,
        loadingMore: inbox.isFetchingNextPage,
        loadMore: () => void inbox.fetchNextPage(),
        retry: () => void inbox.refetch(),
      },
      similar: {
        degraded: similar.data?.tier_used === "degraded",
        hiddenIneligible: similar.data?.meta.hidden_ineligible ?? 0,
        isError: similar.isError,
      },
      // Awaria silnika nie może zostawić rekrutera bez wyjścia: jedno „Ponów"
      // odświeża wszystko, z czego powstała lista (skrzynka, podobne projekty
      // i odczyt przeglądu bazy).
      retryEngine: () => {
        void inbox.refetch();
        void similar.refetch();
        retryRun();
      },
      recommendations: {
        degraded: recommendations.data?.degraded === true,
        stale: recommendations.data?.stale === true,
        pending: recommendations.data?.status === "pending",
        isError: recommendations.isError,
        regenerate: () => regenerate.mutate(),
        regenerating: regenerate.isPending,
      },
    },
    addToJob: useCallback(
      (candidateIds: number[], opts: AddToJobOptions = {}) => addMutate({ candidateIds, opts }),
      [addMutate],
    ),
    adding: addMutation.isPending,
    dismiss: useCallback((candidateIds: number[]) => dismissMutate(candidateIds), [dismissMutate]),
    dismissing: dismissMutation.isPending,
    addToShortlist: useCallback((candidateIds: number[]) => shortlistMutate(candidateIds), [shortlistMutate]),
    shortlisting: shortlistMutation.isPending,
  };
}

export type JobProposalsState = ReturnType<typeof useJobProposals>;
