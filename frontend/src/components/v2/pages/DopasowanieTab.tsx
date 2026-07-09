"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Loader2,
  RefreshCw,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { Button } from "@/components/ui";
import {
  extractErrorMsg,
  matchScoringApi,
  type MatchJustification,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";

interface Recruitment {
  job_id: number;
  job_title?: string | null;
}

interface DopasowanieTabProps {
  candidateId: number;
  /** The candidate's recruitments (from /history) — the jobs we can score against. */
  recruitments: Recruitment[];
  /** Preselect the job the profile was opened from (`?from=job&jobId=N`). */
  defaultJobId?: number | null;
}

/** Ring colour by score band — mirrors the kanban / marketplace score bands. */
function ringColorClass(score: number): string {
  if (score >= 80) return "text-emerald-500";
  if (score >= 65) return "text-primary";
  if (score >= 45) return "text-amber-500";
  return "text-muted-foreground";
}

function ScoreRing({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(score)));
  const radius = 34;
  const circumference = 2 * Math.PI * radius;
  const dash = (pct / 100) * circumference;
  return (
    <div className="relative h-24 w-24 shrink-0" aria-label={`Dopasowanie ${pct} na 100`}>
      <svg viewBox="0 0 80 80" className="h-24 w-24 -rotate-90">
        <circle
          cx="40"
          cy="40"
          r={radius}
          className="fill-none stroke-muted"
          strokeWidth="7"
        />
        <circle
          cx="40"
          cy="40"
          r={radius}
          className={cn("fill-none transition-all", ringColorClass(pct))}
          stroke="currentColor"
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold tabular-nums leading-none text-foreground">
          {pct}
        </span>
        <span className="mt-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          / 100
        </span>
      </div>
    </div>
  );
}

export function DopasowanieTab({
  candidateId,
  recruitments,
  defaultJobId,
}: DopasowanieTabProps) {
  const { showError, showSuccess } = useToast();
  const queryClient = useQueryClient();

  // De-dupe recruitments by job (a candidate can have several stage rows per job).
  const jobs = useMemo(() => {
    const seen = new Set<number>();
    const out: Recruitment[] = [];
    for (const r of recruitments) {
      if (r?.job_id == null || seen.has(r.job_id)) continue;
      seen.add(r.job_id);
      out.push(r);
    }
    return out;
  }, [recruitments]);

  const [jobId, setJobId] = useState<number | null>(
    defaultJobId ?? jobs[0]?.job_id ?? null,
  );

  // Once recruitments load (or the default resolves after hydration), pick a job.
  useEffect(() => {
    if (jobId != null) return;
    const next = defaultJobId ?? jobs[0]?.job_id ?? null;
    if (next != null) setJobId(next);
  }, [jobId, defaultJobId, jobs]);

  const queryKey = ["match-justification", candidateId, jobId] as const;

  const query = useQuery<MatchJustification>({
    queryKey,
    queryFn: () => matchScoringApi.get(candidateId, jobId!).then((r) => r.data),
    enabled: jobId != null,
    retry: false,
    staleTime: 5 * 60_000,
  });

  const refreshMut = useMutation({
    mutationFn: () =>
      matchScoringApi
        .get(candidateId, jobId!, { refresh: true })
        .then((r) => r.data),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKey, data);
      showSuccess("Uzasadnienie odświeżone");
    },
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się odświeżyć"),
  });

  const feedbackMut = useMutation({
    mutationFn: (rating: number) =>
      matchScoringApi
        .feedback(candidateId, jobId!, { rating })
        .then((r) => r.data),
    onSuccess: (data) => queryClient.setQueryData(queryKey, data),
    onError: (e) => showError(extractErrorMsg(e) || "Nie udało się zapisać oceny"),
  });

  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border bg-muted/30 px-6 py-12 text-center">
        <Sparkles className="h-6 w-6 text-muted-foreground" />
        <p className="text-sm font-medium text-foreground">
          Brak rekrutacji do oceny
        </p>
        <p className="max-w-sm text-sm text-muted-foreground">
          Przypisz kandydata do oferty (przycisk „Przypisz do oferty"), aby AI
          mogło policzyć i uzasadnić dopasowanie.
        </p>
      </div>
    );
  }

  const data = query.data;
  const busy = query.isLoading || refreshMut.isPending;
  const currentRating = data?.rating ?? 0;

  const setRating = (value: number) => {
    if (feedbackMut.isPending) return;
    // Clicking the active thumb again resets the rating (send 0).
    feedbackMut.mutate(currentRating === value ? 0 : value);
  };

  return (
    <div className="space-y-5">
      {/* Job selector + refresh */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex min-w-0 items-center gap-2 text-sm">
          <span className="shrink-0 font-medium text-muted-foreground">
            Oferta:
          </span>
          <select
            value={jobId ?? ""}
            onChange={(e) => setJobId(Number(e.target.value))}
            className="min-w-0 max-w-full truncate rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
          >
            {jobs.map((j) => (
              <option key={j.job_id} value={j.job_id}>
                {j.job_title || `Oferta #${j.job_id}`}
              </option>
            ))}
          </select>
        </label>
        <Button
          variant="outline"
          size="sm"
          onClick={() => refreshMut.mutate()}
          disabled={busy || jobId == null}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", refreshMut.isPending && "animate-spin")} />
          Odśwież
        </Button>
      </div>

      {/* Loading (first generation calls the LLM — can take a few seconds) */}
      {busy && !data && (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-border bg-card/60 px-6 py-12 text-center">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <p className="text-sm font-medium text-foreground">
            Generuję uzasadnienie AI…
          </p>
          <p className="text-xs text-muted-foreground">
            Pierwsze wygenerowanie może potrwać kilka sekund.
          </p>
        </div>
      )}

      {/* Error (AI disabled / generation failed) */}
      {query.isError && !data && (
        <div className="flex flex-col items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-5 dark:border-amber-900/50 dark:bg-amber-950/30">
          <div className="flex items-center gap-2 text-sm font-medium text-amber-800 dark:text-amber-300">
            <AlertTriangle className="h-4 w-4" />
            Nie udało się przygotować uzasadnienia
          </div>
          <p className="text-sm text-amber-800/90 dark:text-amber-200/80">
            {extractErrorMsg(query.error)}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => query.refetch()}
            disabled={query.isFetching}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} />
            Spróbuj ponownie
          </Button>
        </div>
      )}

      {/* Result */}
      {data && (
        <div className="space-y-5">
          {/* Score + summary */}
          <div className="flex flex-col gap-4 rounded-xl border border-border bg-card/60 p-5 sm:flex-row sm:items-start">
            <ScoreRing score={data.score} />
            <div className="min-w-0 flex-1">
              <h3 className="mb-1.5 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Podsumowanie
              </h3>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                {data.summary || "Brak podsumowania."}
              </p>
            </div>
          </div>

          {/* Pros */}
          {data.pros.length > 0 && (
            <section className="rounded-xl border border-border bg-card/60 p-5">
              <h3 className="mb-3 text-sm font-semibold text-emerald-700 dark:text-emerald-400">
                Może być dobrym wyborem, ponieważ:
              </h3>
              <ul className="space-y-2">
                {data.pros.map((p, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    <span>{p}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Watch-outs */}
          {data.watchouts.length > 0 && (
            <section className="rounded-xl border border-border bg-card/60 p-5">
              <h3 className="mb-3 text-sm font-semibold text-amber-700 dark:text-amber-400">
                Do weryfikacji / luki:
              </h3>
              <ul className="space-y-2">
                {data.watchouts.map((w, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Feedback + provenance */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Oceń ten scoring:</span>
              <Button
                variant={currentRating === 1 ? "primary" : "outline"}
                size="sm"
                onClick={() => setRating(1)}
                disabled={feedbackMut.isPending}
                aria-pressed={currentRating === 1}
                aria-label="Trafny scoring"
              >
                <ThumbsUp className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant={currentRating === -1 ? "destructive" : "outline"}
                size="sm"
                onClick={() => setRating(-1)}
                disabled={feedbackMut.isPending}
                aria-pressed={currentRating === -1}
                aria-label="Nietrafny scoring"
              >
                <ThumbsDown className="h-3.5 w-3.5" />
              </Button>
            </div>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Sparkles className="h-3 w-3" />
              Wygenerowane przez AI{data.model ? ` (${data.model})` : ""} — zweryfikuj
              przed decyzją.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

export default DopasowanieTab;
