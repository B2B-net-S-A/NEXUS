"use client";

import { useEffect, useState } from "react";
import { X, Sparkles, Briefcase, Loader2, CheckCircle2 } from "lucide-react";
import { recommendationsApi, JobMatch } from "@/lib/api";

interface QuickAssignModalProps {
  candidateId: number;
  candidateName: string;
  onClose: () => void;
  /** Invoked after a successful assignment so the list can refetch badges. */
  onAssigned?: (jobId: number) => void;
}

function scoreBadgeColor(score: number): string {
  if (score >= 75) return "bg-emerald-100 text-emerald-700 border-emerald-300";
  if (score >= 60) return "bg-blue-100 text-blue-700 border-blue-300";
  if (score >= 40) return "bg-amber-100 text-amber-700 border-amber-300";
  return "bg-gray-100 text-gray-600 border-gray-300";
}

export function QuickAssignModal({
  candidateId,
  candidateName,
  onClose,
  onAssigned,
}: QuickAssignModalProps) {
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [assigning, setAssigning] = useState<number | null>(null);
  const [assignedIds, setAssignedIds] = useState<Set<number>>(new Set());

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await recommendationsApi.forCandidate(candidateId, {
          top_k: 10,
          include_breakdown: true,
        });
        if (!cancelled) setMatches(res.data.matches);
      } catch (e: unknown) {
        if (cancelled) return;
        const msg =
          e && typeof e === "object" && "response" in e
            ? ((e as { response?: { data?: { detail?: string } } }).response?.data?.detail ?? "Błąd")
            : "Błąd";
        setError(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [candidateId]);

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleAssign = async (jobId: number) => {
    setAssigning(jobId);
    try {
      await recommendationsApi.assignToJob(candidateId, jobId);
      setAssignedIds((prev) => {
        const next = new Set(prev);
        next.add(jobId);
        return next;
      });
      onAssigned?.(jobId);
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
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 sm:p-8 overflow-y-auto"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="quick-assign-title"
    >
      <div
        className="w-full max-w-xl bg-white dark:bg-gray-800 rounded-xl shadow-xl mt-10"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-500" aria-hidden />
            <div>
              <h2
                id="quick-assign-title"
                className="font-semibold text-gray-900 dark:text-gray-100 text-base"
              >
                Przypisz do rekrutacji
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400">{candidateName}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-md"
            aria-label="Zamknij"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center py-10 text-gray-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          )}

          {error && !loading && (
            <div className="rounded bg-red-50 border border-red-200 p-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {!loading && !error && matches.length === 0 && (
            <p className="text-sm text-gray-500 text-center py-8">
              Nie znaleziono pasujących rekrutacji. Upewnij się, że są opublikowane oferty
              i kandydat ma wgrane CV.
            </p>
          )}

          <ul className="space-y-2">
            {matches.map((m) => {
              const j = m.job;
              const assigned = assignedIds.has(j.id);
              return (
                <li
                  key={j.id}
                  className="flex items-center gap-3 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 px-3 py-2.5"
                  data-testid={`quick-assign-job-${j.id}`}
                >
                  <Briefcase className="w-4 h-4 text-gray-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm text-gray-800 dark:text-gray-100 truncate">
                      {j.title}
                    </p>
                    <div className="text-[11px] text-gray-500 flex items-center gap-2 mt-0.5">
                      {j.location && <span>📍 {j.location}</span>}
                      {j.salary_min && j.salary_max && (
                        <span>
                          💰 {j.salary_min.toLocaleString()}–{j.salary_max.toLocaleString()} PLN
                        </span>
                      )}
                      {j.seniority && <span>🎯 {j.seniority}</span>}
                    </div>
                  </div>
                  <span
                    className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${scoreBadgeColor(m.total_score)}`}
                  >
                    {m.total_score.toFixed(0)}
                  </span>
                  <button
                    onClick={() => handleAssign(j.id)}
                    disabled={assigning === j.id || assigned}
                    className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
                      assigned
                        ? "bg-green-100 text-green-700 border-green-300"
                        : "bg-blue-600 text-white border-blue-600 hover:bg-blue-700 disabled:opacity-50"
                    }`}
                    data-testid={`quick-assign-button-${j.id}`}
                  >
                    {assigned ? (
                      <span className="inline-flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Przypisany
                      </span>
                    ) : assigning === j.id ? (
                      "…"
                    ) : (
                      "Przypisz"
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="px-5 py-3 border-t border-gray-200 dark:border-gray-700 flex justify-end">
          <button
            onClick={onClose}
            className="text-sm px-3 py-1.5 text-gray-600 hover:text-gray-800 dark:text-gray-300"
          >
            Zamknij
          </button>
        </div>
      </div>
    </div>
  );
}
