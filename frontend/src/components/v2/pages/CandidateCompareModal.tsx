"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Loader2, Minus, RotateCcw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { candidateSearchApi } from "@/lib/candidate-search-api";
import {
  compareSkillRows,
  type CompareStatus,
} from "@/lib/match-breakdown";
import {
  RATE_LIMIT_MAX_AUTO_RETRIES,
  RATE_LIMIT_RETRY_BASE_MS,
  isRateLimited,
  scoreFailureFor,
} from "@/hooks/useVisibleMatchScores";

export interface CompareCandidate {
  id: number;
  name: string;
}

interface CandidateCompareModalProps {
  jobId: number;
  candidates: CompareCandidate[];
  onClose: () => void;
}

function StatusCell({ status }: { status: CompareStatus }) {
  if (status === "matched")
    return <Check className="mx-auto h-4 w-4 text-emerald-600 dark:text-emerald-400" />;
  if (status === "gap")
    return <X className="mx-auto h-4 w-4 text-rose-500 dark:text-rose-400" />;
  return <Minus className="mx-auto h-3 w-3 text-zinc-300 dark:text-zinc-600" />;
}

function CompareError({
  error,
  retrying,
  onRetry,
}: {
  error: unknown;
  retrying: boolean;
  onRetry: () => void;
}) {
  if (scoreFailureFor(error) === "forbidden") {
    return (
      <p role="alert" className="py-6 text-center text-sm text-muted-foreground">
        Brak dostępu do oceny dopasowania dla tej rekrutacji.
      </p>
    );
  }
  return (
    <div role="alert" className="flex flex-col items-center gap-3 py-6 text-sm">
      <p className="text-center text-muted-foreground">
        {isRateLimited(error)
          ? "Zbyt wiele zapytań o dopasowanie — ponów za chwilę."
          : "Nie udało się policzyć dopasowania."}
      </p>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={onRetry}
        disabled={retrying}
      >
        {retrying ? (
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
        ) : (
          <RotateCcw className="h-3 w-3" aria-hidden="true" />
        )}
        Ponów
      </Button>
    </div>
  );
}

/**
 * Request-aware compare (SEARCH-P1-06): a candidate × requirement matrix for
 * 2–5 shortlisted/selected candidates, built from the canonical fit
 * breakdowns (measured on demand, read-only). Shows the request-fit score plus
 * matched/missing must & nice skills side by side.
 *
 * Measured once per opening, keyed on the ids (not on the array the parent
 * rebuilds every render), cancelled when the modal closes. A failed
 * measurement is an error with "Ponów" — never "Brak kryteriów", which would
 * tell the recruiter the request has no requirements.
 */
export function CandidateCompareModal({
  jobId,
  candidates,
  onClose,
}: CandidateCompareModalProps) {
  const idsKey = candidates.map((c) => c.id).join(",");
  const ids = useMemo(
    () => (idsKey ? idsKey.split(",").map(Number) : []),
    [idsKey],
  );
  const query = useQuery({
    queryKey: ["candidate-compare-scores", jobId, idsKey],
    queryFn: ({ signal }) => candidateSearchApi.matchScores(jobId, ids, { signal }),
    // On-demand and rate-limited: measured when the modal opens, not on
    // focus/reconnect, and not kept after it closes (a later opening may be
    // under another weight profile).
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    retry: (failureCount, error) =>
      isRateLimited(error) && failureCount < RATE_LIMIT_MAX_AUTO_RETRIES,
    retryDelay: (attempt) => RATE_LIMIT_RETRY_BASE_MS * 2 ** attempt,
  });

  const breakdowns = query.data?.breakdowns ?? {};
  const mustRows = compareSkillRows(ids, breakdowns, "must");
  const niceRows = compareSkillRows(ids, breakdowns, "nice");
  const hasAny = mustRows.length > 0 || niceRows.length > 0;
  const waitingForRateLimit = query.isPending && isRateLimited(query.failureReason);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-xl bg-card p-4 shadow-xl dark:border dark:border-zinc-800"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">
            Porównanie do requestu ({candidates.length})
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Zamknij"
            className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {query.isError ? (
          <CompareError
            error={query.error}
            retrying={query.isFetching}
            onRetry={() => void query.refetch()}
          />
        ) : !query.isSuccess ? (
          <div
            role="status"
            className="flex items-center justify-center gap-2 py-6 text-sm text-zinc-500"
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            {waitingForRateLimit
              ? "Zbyt wiele zapytań — ponawiam za chwilę…"
              : "Ładowanie…"}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b dark:border-zinc-800">
                  <th className="p-2 text-left font-medium" />
                  {candidates.map((c) => (
                    <th
                      key={c.id}
                      className="min-w-24 p-2 text-center font-medium"
                    >
                      {c.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-b dark:border-zinc-800">
                  <td className="p-2 font-medium">Dopasowanie</td>
                  {candidates.map((c) => (
                    <td
                      key={c.id}
                      className="p-2 text-center font-semibold tabular-nums"
                    >
                      {query.data.scores?.[String(c.id)] ?? "—"}
                    </td>
                  ))}
                </tr>
                {mustRows.length > 0 && (
                  <tr className="bg-muted/40">
                    <td
                      colSpan={candidates.length + 1}
                      className="px-2 py-1 text-xs font-medium text-zinc-500 dark:text-zinc-400"
                    >
                      Wymagane
                    </td>
                  </tr>
                )}
                {mustRows.map((row) => (
                  <tr key={`must-${row.skill}`} className="border-b dark:border-zinc-800">
                    <td className="p-2">{row.skill}</td>
                    {candidates.map((c) => (
                      <td key={c.id} className="p-2">
                        <StatusCell status={row.status[c.id]} />
                      </td>
                    ))}
                  </tr>
                ))}
                {niceRows.length > 0 && (
                  <tr className="bg-muted/40">
                    <td
                      colSpan={candidates.length + 1}
                      className="px-2 py-1 text-xs font-medium text-zinc-500 dark:text-zinc-400"
                    >
                      Mile widziane
                    </td>
                  </tr>
                )}
                {niceRows.map((row) => (
                  <tr key={`nice-${row.skill}`} className="border-b dark:border-zinc-800">
                    <td className="p-2">{row.skill}</td>
                    {candidates.map((c) => (
                      <td key={c.id} className="p-2">
                        <StatusCell status={row.status[c.id]} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {!hasAny && (
              <p className="py-4 text-center text-xs text-zinc-500 dark:text-zinc-400">
                Brak kryteriów do porównania — rekrutacja nie ma wymagań albo
                wybrani kandydaci nie mają jeszcze pomiaru dopasowania.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
