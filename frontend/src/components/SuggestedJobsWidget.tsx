"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Briefcase, Loader2, RefreshCcw, Sparkles } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api, {
  extractErrorMsg,
  recommendationsApi,
  type JobMatch,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MatchScoreBadge } from "@/components/ds/MatchScoreBadge";
import { useToast } from "@/components/Toast";
import { ScoreBreakdownTooltip } from "./ScoreBreakdownTooltip";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

interface Props {
  candidateId: number;
  /** Cap the number of matches shown. Default 10. */
  maxItems?: number;
  /** Full card or the reduced drawer/rail presentation. */
  variant?: "full" | "compact";
  /** Jump to the matching section in the full profile. */
  onShowAll?: () => void;
  /** Pre-computed results used by the ephemeral CV-upload preview. */
  matches?: JobMatch[];
  /** Collapse the widget when the recommendation service returns no rows. */
  hideWhenEmpty?: boolean;
  /** Optional integration hook after a successful assignment. */
  onAssigned?: (jobId: number) => void;
}

function ScoreChip({ score }: { score: number }) {
  return <MatchScoreBadge score={score} size="sm" className="shrink-0" />;
}

export function SuggestedJobsWidget({
  candidateId,
  maxItems = 10,
  variant = "full",
  onShowAll,
  matches: externalMatches,
  hideWhenEmpty = false,
  onAssigned,
}: Props) {
  const usingExternal = externalMatches !== undefined;
  const topK = Math.max(maxItems, 10);
  const compact = variant === "compact";
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const [assignedIds, setAssignedIds] = useState<Set<number>>(new Set());

  const recommendations = useQuery({
    queryKey: candidateQueryKeys.recommendations(candidateId, topK),
    queryFn: ({ signal }) =>
      api
        .get<{ matches: JobMatch[] }>(
          `/api/candidates/${candidateId}/recommendations`,
          {
            params: { top_k: topK, include_breakdown: true },
            signal,
          },
        )
        .then((response) => response.data.matches),
    enabled: !usingExternal && candidateId > 0,
    staleTime: 30_000,
  });

  const matches = useMemo(
    () =>
      (usingExternal ? externalMatches : recommendations.data ?? []).slice(
        0,
        maxItems,
      ),
    [externalMatches, maxItems, recommendations.data, usingExternal],
  );

  const assign = useMutation({
    mutationFn: (jobId: number) =>
      recommendationsApi.assignToJob(candidateId, jobId),
    onSuccess: (_response, jobId) => {
      setAssignedIds((previous) => new Set(previous).add(jobId));
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.history(candidateId),
      });
      queryClient.invalidateQueries({
        queryKey: ["candidate-pipelines", candidateId],
      });
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.recommendationsRoot(candidateId),
      });
      queryClient.invalidateQueries({ queryKey: ["candidates-v2"] });
      onAssigned?.(jobId);
      showSuccess("Kandydat przypisany do rekrutacji");
    },
    onError: (error) =>
      showError(
        extractErrorMsg(error) || "Nie udało się przypisać do rekrutacji",
      ),
  });

  const loading = !usingExternal && recommendations.isPending;
  const error = !usingExternal ? recommendations.error : null;

  if (hideWhenEmpty && !loading && matches.length === 0 && !error) return null;

  return (
    <section
      className={
        compact
          ? "rounded-xl border border-border bg-card"
          : "rounded-xl border border-border bg-card p-4"
      }
      aria-labelledby={`suggested-jobs-${candidateId}`}
      data-testid="suggested-jobs-widget"
    >
      <div
        className={
          compact
            ? "flex items-center justify-between gap-3 border-b border-border px-4 py-3"
            : "mb-3 flex items-center justify-between gap-3"
        }
      >
        <h3
          id={`suggested-jobs-${candidateId}`}
          className="flex items-center gap-2 text-sm font-semibold text-foreground"
        >
          <Sparkles className="h-4 w-4 text-primary" />
          Sugerowane rekrutacje
        </h3>
        <div className="flex items-center gap-2">
          {onShowAll && matches.length > 0 ? (
            <Button size="sm" variant="ghost" onClick={onShowAll}>
              Zobacz wszystkie
            </Button>
          ) : null}
          {!compact && !usingExternal ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => recommendations.refetch()}
              disabled={recommendations.isFetching}
              aria-label="Odśwież sugerowane rekrutacje"
            >
              <RefreshCcw
                className={
                  recommendations.isFetching
                    ? "h-4 w-4 animate-spin"
                    : "h-4 w-4"
                }
              />
            </Button>
          ) : null}
        </div>
      </div>

      <div className={compact ? "p-3" : undefined}>
        {error ? (
          <div
            role="alert"
            className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
          >
            <span>
              {extractErrorMsg(error) || "Nie udało się pobrać rekomendacji"}
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => recommendations.refetch()}
            >
              Ponów
            </Button>
          </div>
        ) : null}

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Analizuję dopasowanie…
          </div>
        ) : null}

        {!loading && !error && matches.length === 0 ? (
          <p className="py-5 text-center text-sm text-muted-foreground">
            Brak sugerowanych rekrutacji. Uzupełnij CV lub umiejętności
            kandydata.
          </p>
        ) : null}

        {matches.length > 0 ? (
          <ul className="divide-y divide-border" aria-label="Rekomendowane rekrutacje">
            {matches.map((match) => {
              const job = match.job;
              const assigned = assignedIds.has(job.id);
              const assigning = assign.isPending && assign.variables === job.id;
              const strength = match.breakdown?.matching_must?.slice(0, 2) ?? [];
              const gap = match.breakdown?.gap_must?.[0] ?? null;

              return (
                <li
                  key={job.id}
                  className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center"
                  data-testid={`suggested-job-${job.id}`}
                >
                  <div className="flex min-w-0 flex-1 gap-3">
                    <div className="mt-0.5 rounded-lg bg-muted p-2 text-muted-foreground">
                      <Briefcase className="h-4 w-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Link
                          href={`/jobs/${job.id}`}
                          className="truncate text-sm font-semibold text-foreground hover:text-primary hover:underline"
                        >
                          {job.title}
                        </Link>
                        {job.status === "draft" ? (
                          <Badge size="sm" variant="warning">
                            Szkic
                          </Badge>
                        ) : null}
                      </div>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {[job.location, job.seniority].filter(Boolean).join(" · ") ||
                          "Szczegóły w rekrutacji"}
                      </p>
                      {match.breakdown && (strength.length > 0 || gap) ? (
                        <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                          {strength.length > 0
                            ? `Mocne strony: ${strength.join(", ")}`
                            : ""}
                          {strength.length > 0 && gap ? " · " : ""}
                          {gap ? `Luka: ${gap}` : ""}
                        </p>
                      ) : null}
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center justify-end gap-2">
                    <ScoreChip score={match.total_score} />
                    {match.breakdown ? (
                      <ScoreBreakdownTooltip breakdown={match.breakdown} compact />
                    ) : null}
                    {candidateId > 0 ? (
                      <Button
                        size="sm"
                        variant={assigned ? "outline" : "secondary"}
                        onClick={() => assign.mutate(job.id)}
                        disabled={assigning || assigned}
                        data-testid={`assign-to-job-${job.id}`}
                      >
                        {assigned ? "Przypisany" : assigning ? "Przypisuję…" : "Przypisz"}
                      </Button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : null}
      </div>
    </section>
  );
}
