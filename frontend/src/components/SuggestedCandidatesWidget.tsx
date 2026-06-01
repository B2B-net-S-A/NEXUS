"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Loader2, Sparkles, RefreshCw, UserPlus, Star } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import {
  proposalsApi,
  recommendationsApi,
  matchHistoryApi,
  type CandidateMatch,
  type ProposalSnapshot,
} from "@/lib/api";
import { ScoreBreakdownTooltip } from "./ScoreBreakdownTooltip";

interface Props {
  jobId: number;
}

const PENDING_POLL_MS = 2000;

type Mode = "snapshot" | "fallback-live";

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

function snapshotToMatches(snap: ProposalSnapshot): CandidateMatch[] {
  return snap.candidates.map((item) => ({
    candidate: {
      id: item.candidate.id,
      name: item.candidate.name ?? "",
      lastname: item.candidate.lastname ?? "",
      email: item.candidate.email,
      location: item.candidate.location,
      champion: item.candidate.champion ?? false,
      salary_expectation: item.candidate.salary_expectation,
      salary_currency: item.candidate.salary_currency,
      years_it_experience: item.candidate.years_it_experience,
      competence_category: item.candidate.competence_category,
      avatar_url: item.candidate.avatar_url,
    },
    total_score: item.total_score,
    breakdown: item.breakdown,
  }));
}

export function SuggestedCandidatesWidget({ jobId }: Props) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("snapshot");

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
          // No snapshot yet – fall back to the live recommendation path.
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
  // Show ALL candidates that fit – the backend applies the match-quality
  // threshold; this is only a payload safety cap (was a user-facing "Top N"
  // selector, removed when the product shifted to "show everyone who matches").
  const topK = 200;
  const [regenerating, setRegenerating] = useState(false);

  const [assigning, setAssigning] = useState<number | null>(null);
  const [assigned, setAssigned] = useState<Set<number>>(new Set());

  const loadLive = async () => {
    setLiveLoading(true);
    setLiveError(null);
    try {
      const r = await recommendationsApi.forJob(jobId, {
        top_k: topK,
        include_breakdown: true,
      });
      const got = r.data.matches ?? [];
      setLiveMatches(got);
      setLiveLoaded(true);
      await Promise.allSettled(
        got.slice(0, 3).map((m) =>
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
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      alert(`Nie przypisano: ${msg}`);
    } finally {
      setAssigning(null);
    }
  };

  // Log top-3 to match history once a snapshot becomes ready (same UX as live).
  useEffect(() => {
    if (!isSnapReady || !snapshot) return;
    void Promise.allSettled(
      snapshotMatches.slice(0, 3).map((m) =>
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

  const matches = mode === "snapshot" ? snapshotMatches : liveMatches;
  const showLiveEmptyState =
    mode === "fallback-live" && !liveLoaded && !liveLoading;
  const showLiveNoResults =
    mode === "fallback-live" && liveLoaded && liveMatches.length === 0 && !liveLoading;
  const displayError =
    (mode === "snapshot" && isSnapFailed
      ? snapshot?.error_message || "AI nie wygenerowało propozycji"
      : null) ?? liveError;

  return (
    <div
      id="ai-proposals-section"
      className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4"
    >
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <h3 className="font-medium flex items-center gap-2 text-foreground dark:text-foreground">
          <Sparkles className="w-4 h-4 text-violet-500" />
          Rekomendowani kandydaci
          {isSnapReady && (
            <span className="text-xs text-muted-foreground">
              ({snapshotMatches.length})
            </span>
          )}
          {mode === "fallback-live" && liveLoaded && (
            <span className="text-xs text-muted-foreground">({liveMatches.length})</span>
          )}
        </h3>
        <div className="flex items-center gap-2">
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

      {mode === "snapshot" && snapshot && (
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

      {isSnapReady && snapshotMatches.length === 0 && (
        <p className="text-sm text-muted-foreground">
          AI nie znalazło pasujących kandydatów w bazie.
        </p>
      )}

      {isSnapPending && (
        <div className="h-1 w-full bg-violet-100 dark:bg-violet-900/30 rounded-full overflow-hidden mb-2">
          <div className="h-full bg-violet-500 animate-pulse w-1/2" />
        </div>
      )}

      {matches.length > 0 && (
        <ul className="space-y-2">
          {matches.map((m, idx) => {
            const cand = m.candidate;
            const isAssigned = assigned.has(cand.id);
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
                    {cand.location && <span>📍 {cand.location}</span>}
                    {cand.years_it_experience != null && (
                      <span>{cand.years_it_experience}y IT</span>
                    )}
                    {cand.salary_expectation != null && (
                      <span>
                        💰 {cand.salary_expectation.toLocaleString()} {cand.salary_currency ?? "PLN"}
                      </span>
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
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full border font-medium ${scoreColor(
                        m.total_score,
                      )}`}
                    >
                      {m.total_score.toFixed(0)}/100
                    </span>
                    {m.breakdown && <ScoreBreakdownTooltip breakdown={m.breakdown} compact />}
                  </div>
                  {isAssigned ? (
                    <span className="text-[11px] text-emerald-600 font-medium">✓ Przypisany</span>
                  ) : (
                    <button
                      onClick={() => handleAssign(cand.id)}
                      disabled={assigning === cand.id}
                      className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-primary/10 hover:bg-primary/15 text-primary dark:bg-primary/30 dark:text-primary disabled:opacity-50"
                      title="Dodaj do procesu rekrutacji"
                    >
                      {assigning === cand.id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <UserPlus className="w-3 h-3" />
                      )}
                      Przypisz
                    </button>
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
