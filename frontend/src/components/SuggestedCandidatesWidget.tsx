"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Sparkles, RefreshCw, UserPlus, Star, MapPin } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import {
  proposalsApi,
  recommendationsApi,
  matchHistoryApi,
  type CandidateMatch,
  type ProposalSnapshot,
  type RecommendationMeta,
  type ScoreBreakdown,
} from "@/lib/api";
import { LocationInput } from "@/components/v2/filters/LocationInput";
import { assignErrorMessage } from "@/lib/assign-error";
import { shortlistApi } from "@/lib/candidate-search-api";
import { formatCandidateLocation } from "@/components/v2/pages/candidate-list-helpers";
import { ScoreBreakdownTooltip } from "./ScoreBreakdownTooltip";

interface Props {
  jobId: number;
  /** Pre-fill the location filter (e.g. the job's own location). Optional —
   *  imported jobs rarely carry one, so this is usually empty. */
  defaultLocation?: string | null;
}

const PENDING_POLL_MS = 2000;

type Mode = "snapshot" | "fallback-live";

type ScoredCandidateMatch = CandidateMatch & {
  total_score: number;
  breakdown: ScoreBreakdown;
};

/**
 * History accepts only calibrated results.  The meta gate prevents a future
 * degraded response from being persisted even if it accidentally contains a
 * numeric field; the value/schema gate keeps older responses fail-safe.
 */
export function selectMatchesForHistory(
  matches: CandidateMatch[],
  meta?: RecommendationMeta | null,
  limit = 3,
): ScoredCandidateMatch[] {
  if (meta?.degraded) return [];
  return matches
    .filter(
      (match): match is ScoredCandidateMatch =>
        match.total_score !== null && match.breakdown != null,
    )
    .slice(0, limit);
}

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const sec = Math.round(diff / 1000);
  if (sec < 60) return `${sec}s temu`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min temu`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h}h temu`;
  return new Date(iso).toLocaleString("pl-PL");
}

function snapshotToMatches(snap: ProposalSnapshot): ScoredCandidateMatch[] {
  return snap.candidates.map((item) => ({
    candidate: {
      id: item.candidate.id,
      name: item.candidate.name ?? "",
      lastname: item.candidate.lastname ?? "",
      email: item.candidate.email,
      location: item.candidate.location,
      champion: item.candidate.champion ?? false,
      years_it_experience: item.candidate.years_it_experience,
      competence_category: item.candidate.competence_category,
      avatar_url: item.candidate.avatar_url,
    },
    total_score: item.total_score,
    breakdown: item.breakdown,
  }));
}

export function SuggestedCandidatesWidget({ jobId, defaultLocation }: Props) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("snapshot");
  // Show ALL candidates that fit — the backend applies the match-quality
  // threshold; this is only a payload safety cap (was a user-facing "Top N").
  const topK = 200;

  // ── Location filter ───────────────────────────────────────────────────────
  // When the recruiter types a city we bypass the precomputed snapshot and hit
  // the live /recommendations endpoint with `location`: the backend widens the
  // Qdrant pool (located candidates are sparse — ~17% have any location) and
  // filters post-scoring, so we surface located candidates the score-ranked
  // snapshot would otherwise miss. LocationInput already debounces (300 ms).
  const [locationFilter, setLocationFilter] = useState<string>(
    () => defaultLocation?.trim() ?? "",
  );
  const locationActive = locationFilter.trim().length > 0;

  // Dealbreaker-switche: budżet oferty działa Z AUTOMATU jako twardy sufit
  // (decyzja produktowa 19.08) — domyślnie WŁĄCZONY i egzekwowany także
  // w snapshotcie (filtr przy generacji), więc domyślny widok nie wymaga
  // żywego zapytania. Nieznana stawka/preferencja PRZECHODZI po stronie
  // backendu; liczniki ukrytych wracają w meta.hidden / snapshot.hidden
  // i renderują się jako chipy — ukrywanie nigdy nie jest ciche.
  const [excludeOverBudget, setExcludeOverBudget] = useState(true);
  const [excludeRemoteOnly, setExcludeRemoteOnly] = useState(false);
  const [locationSource, setLocationSource] = useState<"all" | "cv" | "notes">(
    "all",
  );
  // Żywe zapytanie filtrowane jest potrzebne wyłącznie przy ODSTĘPSTWIE od
  // semantyki snapshotu (budżet ON, biuro OFF): wyłączenie sufitu budżetu
  // albo włączenie ukrywania tylko-zdalnych. Dzięki temu fast-path Fazy 13
  // zostaje domyślną ścieżką.
  const switchesActive = excludeRemoteOnly || !excludeOverBudget;


  const locationQuery = useQuery({
    queryKey: [
      "recommendations-location",
      jobId,
      locationFilter.trim(),
      locationSource,
      excludeOverBudget,
      excludeRemoteOnly,
    ],
    queryFn: async () => {
      const r = await recommendationsApi.forJob(jobId, {
        top_k: topK,
        include_breakdown: true,
        location: locationFilter.trim() || undefined,
        location_source: locationSource,
        // Jawnie zawsze: backend defaultuje na true, więc wyłączenie sufitu
        // MUSI pojechać jako false — `|| undefined` cofałoby je do defaultu.
        exclude_over_budget: excludeOverBudget,
        exclude_remote_only: excludeRemoteOnly || undefined,
      });
      return r.data;
    },
    enabled: locationActive || switchesActive,
    staleTime: 60_000,
  });

  // ── Snapshot path (Phase 13) ──────────────────────────────────────────────
  const snapshotQuery = useQuery<ProposalSnapshot | null>({
    queryKey: ["proposal-latest", jobId],
    queryFn: async () => {
      try {
        const r = await proposalsApi.latest(jobId);
        return r.data;
      } catch (e) {
        const err = e as AxiosError;
        if (err.response?.status === 404) {
          // No snapshot yet — fall back to the live recommendation path.
          setMode("fallback-live");
          return null;
        }
        throw e;
      }
    },
    refetchInterval: (query) => {
      const data = query.state.data as ProposalSnapshot | null | undefined;
      return data?.status === "pending" ? PENDING_POLL_MS : false;
    },
    retry: 1,
    enabled: mode === "snapshot",
  });

  const snapshot = snapshotQuery.data ?? null;
  const isSnapPending = snapshot?.status === "pending";
  const isSnapReady = snapshot?.status === "ready";
  const isSnapFailed = snapshot?.status === "failed";

  const snapshotMatches = useMemo(
    () => (snapshot ? snapshotToMatches(snapshot) : []),
    [snapshot],
  );

  // ── Fallback live path (legacy) ───────────────────────────────────────────
  const [liveMatches, setLiveMatches] = useState<CandidateMatch[]>([]);
  const [liveLoading, setLiveLoading] = useState(false);
  const [liveLoaded, setLiveLoaded] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [liveMeta, setLiveMeta] = useState<RecommendationMeta | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  const [assigning, setAssigning] = useState<number | null>(null);
  const [assigned, setAssigned] = useState<Set<number>>(new Set());
  const [shortlisting, setShortlisting] = useState<number | null>(null);
  const [shortlisted, setShortlisted] = useState<Set<number>>(new Set());

  const loadLive = async () => {
    setLiveLoading(true);
    setLiveError(null);
    setLiveMeta(null);
    try {
      const r = await recommendationsApi.forJob(jobId, {
        top_k: topK,
        include_breakdown: true,
      });
      const got = r.data.matches ?? [];
      setLiveMatches(got);
      setLiveMeta(r.data.meta ?? null);
      setLiveLoaded(true);
      const historyMatches = selectMatchesForHistory(got, r.data.meta);
      await Promise.allSettled(
        historyMatches.map((m) =>
          matchHistoryApi.log({
            job_id: jobId,
            candidate_id: m.candidate.id,
            total_score: Math.round(m.total_score),
            breakdown: m.breakdown,
          }),
        ),
      );
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      setLiveError(msg);
    } finally {
      setLiveLoading(false);
    }
  };

  const regenerate = async () => {
    setRegenerating(true);
    try {
      await proposalsApi.regenerate(jobId, topK);
      setMode("snapshot");
      await queryClient.invalidateQueries({ queryKey: ["proposal-latest", jobId] });
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      setLiveError(msg);
    } finally {
      setRegenerating(false);
    }
  };

  // ── Assign to pipeline ────────────────────────────────────────────────────
  const handleAssign = async (candidateId: number) => {
    setAssigning(candidateId);
    try {
      await recommendationsApi.assignToJob(candidateId, jobId);
      setAssigned((prev) => {
        const next = new Set(prev);
        next.add(candidateId);
        return next;
      });
    } catch (e: unknown) {
      alert(`Nie przypisano: ${assignErrorMessage(e)}`);
    } finally {
      setAssigning(null);
    }
  };

  // ── Add to shortlist (default action — staged evaluation before pipeline) ──
  const handleShortlist = async (candidateId: number) => {
    setShortlisting(candidateId);
    try {
      await shortlistApi.add(jobId, [candidateId]);
      setShortlisted((prev) => {
        const next = new Set(prev);
        next.add(candidateId);
        return next;
      });
    } catch (e: unknown) {
      alert(`Nie dodano do shortlisty: ${assignErrorMessage(e)}`);
    } finally {
      setShortlisting(null);
    }
  };

  // Log top-3 to match history once a snapshot becomes ready (same UX as live).
  useEffect(() => {
    if (!isSnapReady || !snapshot) return;
    const historyMatches = selectMatchesForHistory(snapshotMatches);
    void Promise.allSettled(
      historyMatches.map((m) =>
        matchHistoryApi.log({
          job_id: jobId,
          candidate_id: m.candidate.id,
          total_score: Math.round(m.total_score),
          breakdown: m.breakdown,
        }),
      ),
    );
  }, [isSnapReady, snapshot, snapshotMatches, jobId]);

  const scoreColor = (s: number) => {
    if (s >= 75) return "bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300";
    if (s >= 50) return "bg-primary/15 text-primary border-primary/30 dark:bg-primary/30 dark:text-primary";
    if (s >= 25) return "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300";
    return "bg-muted text-muted-foreground border-border dark:bg-card/30 dark:text-muted-foreground";
  };

  // Active display source: location filter > snapshot > fallback-live.
  const filteredActive = locationActive || switchesActive;
  const matches = filteredActive
    ? (locationQuery.data?.matches ?? [])
    : mode === "snapshot"
      ? snapshotMatches
      : liveMatches;
  const activeRecommendationMeta = filteredActive
    ? (locationQuery.data?.meta ?? null)
    : mode === "fallback-live"
      ? liveMeta
      : mode === "snapshot" && snapshot?.degraded
        ? {
            mode: "degraded_semantic",
            degraded: true,
            reason: "semantic_unavailable",
          }
        : null;
  const isDegraded = activeRecommendationMeta?.degraded === true;
  // Liczniki ukrytych: ścieżka filtrowana niesie je w meta.hidden, snapshot —
  // w snap.hidden (sufit budżetu działa też przy generacji; null = snapshot
  // sprzed 0237, nieprzefiltrowany, bez chipa).
  const hiddenCounts = filteredActive
    ? (activeRecommendationMeta?.hidden ?? null)
    : mode === "snapshot"
      ? (snapshot?.hidden ?? null)
      : (liveMeta?.hidden ?? null);
  const showLiveEmptyState =
    !filteredActive && mode === "fallback-live" && !liveLoaded && !liveLoading;
  const showLiveNoResults =
    !filteredActive &&
    mode === "fallback-live" &&
    liveLoaded &&
    liveMatches.length === 0 &&
    !liveLoading;
  // Snapshot/live error banner is suppressed while a location filter is active —
  // location mode renders its own loading/empty/error states below.
  const displayError = filteredActive
    ? null
    : ((mode === "snapshot" && isSnapFailed
        ? snapshot?.error_message || "AI nie wygenerowało propozycji"
        : null) ?? liveError);
  const locationLabel = locationQuery.data?.location_filter ?? locationFilter.trim();
  // The badge must reflect what the SERVER actually filtered on, not the raw
  // input. The backend tokenizes the value and applies NO filter (location_filter
  // null) for input that yields no place tokens (e.g. separator-only "/" or ",").
  // Gate the "📍 …" badge on the server's echo so junk input can't paint a
  // location badge over an unfiltered list.
  const serverLocationApplied =
    locationActive && (locationQuery.data?.location_filter ?? null) !== null;
  const showLocationLoading = filteredActive && locationQuery.isLoading;
  const showLocationError = filteredActive && locationQuery.isError;
  const showLocationNoResults =
    locationActive &&
    !locationQuery.isLoading &&
    !locationQuery.isError &&
    matches.length === 0;
  // Ścieżka „tylko switche" (bez tekstu lokalizacji) też musi mieć własny
  // pusty stan — inaczej włączony dealbreaker bez trafień renderuje pustą
  // kartę bez słowa wyjaśnienia (reguła „awaria ≠ pustka"). Regułę złamałem
  // w tym samym PR-ze, w którym ją cytuję — stąd ta gałąź.
  const showSwitchesNoResults =
    switchesActive &&
    !locationActive &&
    !locationQuery.isLoading &&
    !locationQuery.isError &&
    matches.length === 0;

  return (
    <div
      id="ai-proposals-section"
      className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4"
    >
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <h3 className="font-medium flex items-center gap-2 flex-wrap text-foreground dark:text-foreground">
          <Sparkles className="w-4 h-4 text-violet-500" />
          Rekomendowani kandydaci
          {!filteredActive && isSnapReady && (
            <span className="text-xs text-muted-foreground">
              ({snapshotMatches.length})
            </span>
          )}
          {!filteredActive && mode === "fallback-live" && liveLoaded && (
            <span className="text-xs text-muted-foreground">({liveMatches.length})</span>
          )}
          {filteredActive && !locationQuery.isLoading && (
            <span className="text-xs text-muted-foreground">({matches.length})</span>
          )}
          {serverLocationApplied && (
            <span className="text-[10px] px-2 py-0.5 bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300 rounded-full font-medium inline-flex items-center gap-1">
              <MapPin className="w-3 h-3" /> {locationQuery.data?.location_filter}
            </span>
          )}
        </h3>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <div className="w-48">
            <LocationInput
              value={locationFilter}
              onChange={setLocationFilter}
              placeholder="Lokalizacja (np. Warszawa)"
            />
            {locationActive && (
              <select
                value={locationSource}
                onChange={(e) =>
                  setLocationSource(e.target.value as "all" | "cv" | "notes")
                }
                className="text-xs border border-border rounded-md px-1.5 py-1 bg-background"
                title="Źródło lokalizacji kandydata"
                data-testid="location-source-select"
              >
                <option value="all">CV + notatki</option>
                <option value="cv">Tylko CV</option>
                <option value="notes">Tylko notatki</option>
              </select>
            )}
            <button
              onClick={() => setExcludeOverBudget((v) => !v)}
              className={`text-xs px-2 py-1 rounded-md border ${
                excludeOverBudget
                  ? "bg-amber-100 border-amber-300 text-amber-900 dark:bg-amber-900/30 dark:border-amber-700 dark:text-amber-200"
                  : "border-border text-muted-foreground hover:bg-accent"
              }`}
              title="Budżet oferty działa jako twardy sufit (domyślnie): kandydaci ze ZNANĄ stawką powyżej niego są ukryci. Nieznana stawka zawsze przechodzi. Kliknij, żeby pokazać też przekraczających."
              data-testid="switch-over-budget"
            >
              {excludeOverBudget
                ? "Poza budżetem: ukryci"
                : "Poza budżetem: widoczni"}
            </button>
            <button
              onClick={() => setExcludeRemoteOnly((v) => !v)}
              className={`text-xs px-2 py-1 rounded-md border ${
                excludeRemoteOnly
                  ? "bg-amber-100 border-amber-300 text-amber-900 dark:bg-amber-900/30 dark:border-amber-700 dark:text-amber-200"
                  : "border-border text-muted-foreground hover:bg-accent"
              }`}
              title="Ukryj kandydatów z potwierdzonym w rozmowach „wyłącznie zdalnie”. Nieznana preferencja zawsze przechodzi."
              data-testid="switch-remote-only"
            >
              Tylko-zdalni: ukryj
            </button>
          </div>
          {mode === "snapshot" ? (
            <button
              onClick={regenerate}
              disabled={regenerating || isSnapPending}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
              data-testid="regenerate-proposals-btn"
            >
              {regenerating || isSnapPending ? (
                <>
                  <Loader2 className="w-3 h-3 animate-spin" /> Analizuję…
                </>
              ) : (
                <>
                  <RefreshCw className="w-3 h-3" /> Odśwież propozycje
                </>
              )}
            </button>
          ) : (
            <button
              onClick={loadLive}
              disabled={liveLoading}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
              data-testid="suggest-candidates-btn"
            >
              {liveLoading ? (
                <>
                  <Loader2 className="w-3 h-3 animate-spin" /> Szukam…
                </>
              ) : liveLoaded ? (
                <>
                  <RefreshCw className="w-3 h-3" /> Odśwież
                </>
              ) : (
                <>
                  <Sparkles className="w-3 h-3" /> Sugeruj kandydatów
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {!filteredActive && mode === "snapshot" && snapshot && (
        <div className="text-xs text-muted-foreground dark:text-muted-foreground mb-3">
          {isSnapReady && (
            <>
              AI zaproponowało {snapshotMatches.length} kandydatów ·{" "}
              {formatRelative(snapshot.created_at)}
            </>
          )}
          {isSnapPending && (
            <span className="flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin text-violet-500" />
              AI analizuje bazę kandydatów… (zazwyczaj &lt; 10s)
            </span>
          )}
        </div>
      )}

      {mode === "snapshot" && snapshot?.stale && (
        <div
          role="status"
          data-testid="stale-ranking-notice"
          className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted px-3 py-2 text-xs text-foreground"
        >
          <span>
            Brief lub Profil Championa zmienił się po wygenerowaniu tego rankingu
            — jest nieaktualny.
          </span>
          <button
            type="button"
            onClick={regenerate}
            disabled={regenerating || isSnapPending}
            data-testid="stale-rerun-btn"
            className="rounded-md bg-primary px-2 py-0.5 font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Uruchom ponownie
          </button>
        </div>
      )}

      {(() => {
        const total =
          (hiddenCounts?.over_budget ?? 0) + (hiddenCounts?.remote_only ?? 0);
        if (!total) return null;
        // Ukrywanie nigdy nie jest ciche: pustka bez wyjaśnienia czyta się
        // jak utrata danych (reguła „awaria ≠ pustka").
        return (
          <div
            role="status"
            data-testid="dealbreaker-hidden-notice"
            className="mb-3 flex flex-wrap gap-2 text-xs"
          >
            {(hiddenCounts?.over_budget ?? 0) > 0 && (
              <span className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-amber-900 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
                Ukryto {hiddenCounts!.over_budget} powyżej budżetu oferty
              </span>
            )}
            {(hiddenCounts?.remote_only ?? 0) > 0 && (
              <span className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-amber-900 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
                Ukryto {hiddenCounts!.remote_only} tylko-zdalnych
              </span>
            )}
          </div>
        );
      })()}

      {isDegraded && (
        <div
          role="status"
          data-testid="degraded-recommendations-notice"
          className="mb-3 rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground"
        >
          {activeRecommendationMeta?.mode === "bm25" ? (
            <>
              Wyszukiwanie działa w trybie awaryjnym BM25. Pokazujemy ranking
              tekstowy bez standardowego wyniku dopasowania; tych wyników nie
              zapisujemy w historii.
            </>
          ) : (
            <>
              Wyszukiwanie semantyczne jest chwilowo niedostępne. Standardowy
              wynik dopasowania nie został wyliczony ani zapisany w historii.
            </>
          )}
        </div>
      )}

      {showLocationLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-6">
          <Loader2 className="w-4 h-4 animate-spin text-violet-500" />
          Szukam kandydatów w lokalizacji „{locationFilter.trim()}”…
        </div>
      )}

      {showLocationError && (
        <p className="text-sm text-destructive py-2">
          Błąd wyszukiwania kandydatów po lokalizacji. Zmień filtr i spróbuj ponownie.
        </p>
      )}

      {showLocationNoResults && (
        <p className="text-sm text-muted-foreground py-2">
          Brak rekomendowanych kandydatów w lokalizacji „{locationLabel}”. Zmień lub
          wyczyść filtr powyżej.
        </p>
      )}

      {showSwitchesNoResults && (
        <p className="text-sm text-muted-foreground py-2">
          Wszyscy rekomendowani kandydaci zostali ukryci przez włączone filtry
          wykluczające. Poluzuj margines budżetu albo wyłącz przełączniki powyżej.
        </p>
      )}

      {displayError && (
        <div className="text-xs text-destructive bg-destructive/10 dark:bg-destructive/15 rounded p-2 mb-2">
          {displayError}
          {isSnapFailed && (
            <button
              onClick={regenerate}
              disabled={regenerating}
              className="ml-2 underline hover:text-red-900"
            >
              Spróbuj ponownie
            </button>
          )}
        </div>
      )}

      {showLiveEmptyState && (
        <p className="text-sm text-muted-foreground">
          Uruchom hybrydowe wyszukiwanie: semantic (Qdrant) + skills match + dopasowanie stawki/lokalizacji.
        </p>
      )}

      {showLiveNoResults && (
        <p className="text-sm text-muted-foreground">Nie znaleziono pasujących kandydatów.</p>
      )}

      {!locationActive && isSnapReady && snapshotMatches.length === 0 && (
        <p className="text-sm text-muted-foreground">
          AI nie znalazło pasujących kandydatów w bazie.
        </p>
      )}

      {!locationActive && isSnapPending && (
        <div className="h-1 w-full bg-violet-100 dark:bg-violet-900/30 rounded-full overflow-hidden mb-2">
          <div className="h-full bg-violet-500 animate-pulse w-1/2" />
        </div>
      )}

      {matches.length > 0 && (
        <ul className="space-y-2">
          {matches.map((m, idx) => {
            const cand = m.candidate;
            const isAssigned = assigned.has(cand.id);
            const isShortlisted = shortlisted.has(cand.id);
            return (
              <li
                key={cand.id}
                className="flex items-start gap-3 p-2.5 rounded-lg border border-border dark:border-border hover:border-primary/30 dark:hover:border-primary transition-colors"
              >
                <span className="text-xs text-muted-foreground w-6 text-center mt-1 font-semibold">
                  #{idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/candidates/${cand.id}`}
                      className="font-medium text-foreground dark:text-foreground hover:text-primary truncate"
                    >
                      {cand.name} {cand.lastname}
                    </Link>
                    {cand.champion && (
                      <Star className="w-3.5 h-3.5 fill-yellow-400 text-yellow-400" aria-label="Champion" />
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground mt-0.5">
                    {formatCandidateLocation(cand.location) && (
                      <span>📍 {formatCandidateLocation(cand.location)}</span>
                    )}
                    {cand.years_it_experience != null && (
                      <span>{cand.years_it_experience}y IT</span>
                    )}
                    {cand.competence_category && (
                      <span className="text-[11px]">· {cand.competence_category}</span>
                    )}
                  </div>
                  {m.breakdown && m.breakdown.matching_must.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {m.breakdown.matching_must.slice(0, 4).map((s) => (
                        <span
                          key={s}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                        >
                          ✓ {s}
                        </span>
                      ))}
                      {m.breakdown.matching_must.length > 4 && (
                        <span className="text-[10px] text-muted-foreground">
                          +{m.breakdown.matching_must.length - 4}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex flex-col items-end gap-1">
                  <div className="flex items-center gap-1">
                    {m.total_score === null ? (
                      <span
                        data-testid={`degraded-score-${cand.id}`}
                        className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
                        title="Ranking tekstowy BM25 — standardowy wynik dopasowania jest niedostępny"
                      >
                        BM25 · tryb awaryjny
                      </span>
                    ) : (
                      <span
                        className={`text-xs px-2 py-0.5 rounded-full border font-medium ${scoreColor(
                          m.total_score,
                        )}`}
                      >
                        {m.total_score.toFixed(0)}/100
                      </span>
                    )}
                    {m.breakdown && <ScoreBreakdownTooltip breakdown={m.breakdown} compact />}
                  </div>
                  {isAssigned ? (
                    <span className="text-[11px] text-emerald-600 font-medium">✓ Przypisany</span>
                  ) : isShortlisted ? (
                    <span className="text-[11px] text-emerald-600 font-medium">
                      ✓ Na shortliście
                    </span>
                  ) : (
                    <div className="flex items-center gap-1">
                      {/* Primary action: stage on the shortlist for evaluation
                          before touching the pipeline (add_to_shortlist enforces
                          job membership). "Przypisz" (direct pipeline entry) is
                          the secondary, heavier action. */}
                      <button
                        onClick={() => handleShortlist(cand.id)}
                        disabled={shortlisting === cand.id}
                        className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-primary/10 hover:bg-primary/15 text-primary dark:bg-primary/30 dark:text-primary disabled:opacity-50"
                        title="Dodaj do shortlisty do oceny"
                      >
                        {shortlisting === cand.id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Star className="w-3 h-3" />
                        )}
                        Do shortlisty
                      </button>
                      <button
                        onClick={() => handleAssign(cand.id)}
                        disabled={assigning === cand.id}
                        className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded border border-border text-muted-foreground hover:bg-muted disabled:opacity-50"
                        title="Dodaj bezpośrednio do procesu rekrutacji"
                      >
                        {assigning === cand.id ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <UserPlus className="w-3 h-3" />
                        )}
                        Przypisz
                      </button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
