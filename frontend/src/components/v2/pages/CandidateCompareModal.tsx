"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, Minus, X } from "lucide-react";
import {
  candidateSearchApi,
  type MatchScoresResponse,
} from "@/lib/candidate-search-api";
import {
  compareSkillRows,
  type CompareStatus,
} from "@/lib/match-breakdown";

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

/**
 * Request-aware compare (SEARCH-P1-06): a candidate × requirement matrix for
 * 2–5 shortlisted/selected candidates, built from the cached score breakdowns
 * (read-only). Shows the request-fit score plus matched/missing must & nice
 * skills side by side.
 */
export function CandidateCompareModal({
  jobId,
  candidates,
  onClose,
}: CandidateCompareModalProps) {
  const [data, setData] = useState<MatchScoresResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    candidateSearchApi
      .matchScores(
        jobId,
        candidates.map((c) => c.id),
      )
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, candidates]);

  const ids = candidates.map((c) => c.id);
  const breakdowns = data?.breakdowns ?? {};
  const mustRows = compareSkillRows(ids, breakdowns, "must");
  const niceRows = compareSkillRows(ids, breakdowns, "nice");
  const hasAny = mustRows.length > 0 || niceRows.length > 0;

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

        {loading ? (
          <div className="flex items-center justify-center gap-2 py-6 text-sm text-zinc-500">
            <Loader2 className="h-4 w-4 animate-spin" /> Ładowanie…
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
                      className="min-w-[6rem] p-2 text-center font-medium"
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
                      {data?.scores?.[String(c.id)] ?? "—"}
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
                Brak zapisanych wyników dopasowania dla wybranych kandydatów —
                porównanie skryteriów pojawi się po ich ocenieniu w dopasowaniu.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
