"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Briefcase, Loader2, Sparkles } from "lucide-react";
import { recommendationsApi, JobMatch } from "@/lib/api";
import { ScoreBreakdownTooltip } from "./ScoreBreakdownTooltip";

interface Props {
  candidateId: number;
  /** Cap the number of matches shown. Default 10. */
  maxItems?: number;
  /**
   * "full" — full-height card with title, refresh, and footer details.
   * "compact" — trimmed for headers/sidebars; hides refresh button, shrinks rows.
   */
  variant?: "full" | "compact";
  /** Optional callback to jump to the full matches view (e.g. switch tabs). */
  onShowAll?: () => void;
  /**
   * Optional pre-computed matches. When provided the widget renders these
   * directly instead of fetching `/api/candidates/{id}/recommendations`.
   * Used by the CV-upload-preview flow on /sourcing/seeking-contractors —
   * the candidate is ephemeral, so there is no candidateId-driven fetch path.
   * The "Przypisz do rekrutacji" action is hidden when no candidateId exists
   * (candidateId === 0 acts as a sentinel for the ephemeral case).
   */
  matches?: JobMatch[];
}

function ScoreChip({ score }: { score: number }) {
  const color =
    score >= 80
      ? "bg-green-100 text-green-700 border-green-300"
      : score >= 60
        ? "bg-blue-100 text-blue-700 border-blue-300"
        : score >= 40
          ? "bg-amber-100 text-amber-700 border-amber-300"
          : "bg-gray-100 text-gray-600 border-gray-300";
  return (
    <span
      className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${color}`}
    >
      {score.toFixed(0)}
    </span>
  );
}

export function SuggestedJobsWidget({
  candidateId,
  maxItems = 10,
  variant = "full",
  onShowAll,
  matches: externalMatches,
}: Props) {
  const usingExternal = externalMatches !== undefined;
  const [matches, setMatches] = useState<JobMatch[]>(
    usingExternal ? externalMatches.slice(0, maxItems) : [],
  );
  const [loading, setLoading] = useState(!usingExternal);
  const [error, setError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<number | null>(null);
  const [assignedIds, setAssignedIds] = useState<Set<number>>(new Set());
  const compact = variant === "compact";

  const load = async () => {
    if (usingExternal) {
      setMatches(externalMatches.slice(0, maxItems));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await recommendationsApi.forCandidate(candidateId, {
        top_k: Math.max(maxItems, 10),
        include_breakdown: true,
      });
      setMatches(res.data.matches.slice(0, maxItems));
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [candidateId, usingExternal, externalMatches]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleAssign = async (jobId: number) => {
    setAssigning(jobId);
    try {
      await recommendationsApi.assignToJob(candidateId, jobId);
      setAssignedIds((prev) => new Set(prev).add(jobId));
    } catch (e: unknown) {
      const msg =
        e && typeof e === "object" && "response" in e
          ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
          : "Błąd";
      alert(`Nie udało się przypisać: ${msg}`);
    } finally {
      setAssigning(null);
    }
  };

  return (
    <div
      className={
        compact
          ? "bg-white dark:bg-gray-800 rounded-lg border border-purple-200 dark:border-purple-800/50 p-3"
          : "bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4"
      }
    >
      <div className="flex items-center justify-between mb-2">
        <h3
          className={
            compact
              ? "font-semibold text-xs text-purple-700 dark:text-purple-200 flex items-center gap-1.5 uppercase tracking-wide"
              : "font-medium text-gray-900 dark:text-gray-100 flex items-center gap-2"
          }
        >
          <Sparkles className={compact ? "w-3.5 h-3.5 text-purple-500" : "w-4 h-4 text-purple-500"} />
          Sugerowane rekrutacje
        </h3>
        {compact ? (
          onShowAll && matches.length >= maxItems ? (
            <button
              onClick={onShowAll}
              className="text-[11px] text-blue-600 hover:text-blue-800 dark:text-blue-300"
            >
              Pokaż wszystkie →
            </button>
          ) : null
        ) : (
          <button
            onClick={load}
            className="text-xs text-blue-600 hover:text-blue-800 dark:text-blue-300"
            disabled={loading}
          >
            {loading ? "Ładowanie…" : "Odśwież"}
          </button>
        )}
      </div>

      {error && (
        <div className="rounded bg-red-50 border border-red-200 p-2 text-sm text-red-700 mb-2">
          {error}
        </div>
      )}

      {loading && matches.length === 0 && (
        <div className="flex justify-center py-6">
          <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
        </div>
      )}

      {!loading && matches.length === 0 && (
        <p className="text-sm text-gray-500 py-4 text-center">
          Brak sugerowanych projektów. Upewnij się, że CV zostało wgrane i masz
          opublikowane oferty.
        </p>
      )}

      <ul className="space-y-1.5">
        {matches.map((m) => {
          const j = m.job;
          const assigned = assignedIds.has(j.id);
          return (
            <li
              key={j.id}
              className="flex items-center gap-3 rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 px-3 py-2"
              data-testid={`suggested-job-${j.id}`}
            >
              <Briefcase className="w-4 h-4 text-gray-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <Link
                  href={`/jobs/${j.id}`}
                  className="font-medium text-sm text-gray-800 dark:text-gray-100 hover:underline truncate block"
                >
                  {j.title}
                </Link>
                <div className="text-[11px] text-gray-500 flex items-center gap-2 mt-0.5">
                  {j.location && <span>📍 {j.location}</span>}
                  {j.salary_min && j.salary_max && (
                    <span>
                      💰 {j.salary_min.toLocaleString()}–
                      {j.salary_max.toLocaleString()} PLN
                    </span>
                  )}
                  {j.seniority && <span>🎯 {j.seniority}</span>}
                </div>
              </div>
              <ScoreChip score={m.total_score} />
              {m.breakdown && (
                <ScoreBreakdownTooltip breakdown={m.breakdown} compact />
              )}
              {candidateId === 0 ? null : (
              <button
                onClick={() => handleAssign(j.id)}
                disabled={assigning === j.id || assigned}
                className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
                  assigned
                    ? "bg-green-100 text-green-700 border-green-300"
                    : "bg-blue-600 text-white border-blue-600 hover:bg-blue-700 disabled:opacity-50"
                }`}
                data-testid={`assign-to-job-${j.id}`}
              >
                {assigned
                  ? "✓ Przypisany"
                  : assigning === j.id
                    ? "…"
                    : "Przypisz do rekrutacji"}
              </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
