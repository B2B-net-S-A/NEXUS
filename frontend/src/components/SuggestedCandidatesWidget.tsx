"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2, Sparkles, RefreshCw, UserPlus, Star } from "lucide-react";
import { recommendationsApi, matchHistoryApi, type CandidateMatch } from "@/lib/api";
import { ScoreBreakdownTooltip } from "./ScoreBreakdownTooltip";

interface Props {
  jobId: number;
}

export function SuggestedCandidatesWidget({ jobId }: Props) {
  const [matches, setMatches] = useState<CandidateMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [topK, setTopK] = useState(10);
  const [assigning, setAssigning] = useState<number | null>(null);
  const [assigned, setAssigned] = useState<Set<number>>(new Set());

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await recommendationsApi.forJob(jobId, {
        top_k: topK,
        include_breakdown: true,
      });
      const got = r.data.matches ?? [];
      setMatches(got);
      setLoaded(true);
      // Fire-and-forget: log top-3 to match history for retrospective analysis
      await Promise.allSettled(
        got.slice(0, 3).map(m =>
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
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleAssign = async (candidateId: number) => {
    setAssigning(candidateId);
    try {
      await recommendationsApi.assignToJob(candidateId, jobId);
      setAssigned(prev => {
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

  const scoreColor = (s: number) => {
    if (s >= 75) return "bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-300";
    if (s >= 50) return "bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-900/30 dark:text-blue-300";
    if (s >= 25) return "bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300";
    return "bg-gray-100 text-gray-600 border-gray-300 dark:bg-gray-900/30 dark:text-gray-400";
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <h3 className="font-medium flex items-center gap-2 text-gray-900 dark:text-gray-100">
          <Sparkles className="w-4 h-4 text-violet-500" />
          Rekomendowani kandydaci
          {loaded && <span className="text-xs text-gray-400">({matches.length})</span>}
        </h3>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">
            Top&nbsp;
            <select
              value={topK}
              onChange={e => setTopK(Number(e.target.value))}
              className="rounded border border-gray-300 dark:border-gray-600 px-1.5 py-0.5 text-xs bg-white dark:bg-gray-900"
            >
              <option value={5}>5</option>
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
          </label>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50"
            data-testid="suggest-candidates-btn"
          >
            {loading ? (
              <><Loader2 className="w-3 h-3 animate-spin" /> Szukam…</>
            ) : loaded ? (
              <><RefreshCw className="w-3 h-3" /> Odśwież</>
            ) : (
              <><Sparkles className="w-3 h-3" /> Sugeruj kandydatów</>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div className="text-xs text-red-700 bg-red-50 dark:bg-red-900/20 rounded p-2 mb-2">
          {error}
        </div>
      )}

      {!loaded && !loading && (
        <p className="text-sm text-gray-500">
          Uruchom hybrydowe wyszukiwanie: semantic (Qdrant) + skills match + dopasowanie stawki/lokalizacji.
        </p>
      )}

      {loaded && matches.length === 0 && !loading && (
        <p className="text-sm text-gray-500">Nie znaleziono pasujących kandydatów.</p>
      )}

      {matches.length > 0 && (
        <ul className="space-y-2">
          {matches.map((m, idx) => {
            const cand = m.candidate;
            const isAssigned = assigned.has(cand.id);
            return (
              <li
                key={cand.id}
                className="flex items-start gap-3 p-2.5 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 transition-colors"
              >
                <span className="text-xs text-gray-400 w-6 text-center mt-1 font-semibold">
                  #{idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/candidates/${cand.id}`}
                      className="font-medium text-gray-900 dark:text-gray-100 hover:text-blue-600 truncate"
                    >
                      {cand.name} {cand.lastname}
                    </Link>
                    {cand.champion && (
                      <Star className="w-3.5 h-3.5 fill-yellow-400 text-yellow-400" aria-label="Champion" />
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500 mt-0.5">
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
                      {m.breakdown.matching_must.slice(0, 4).map(s => (
                        <span
                          key={s}
                          className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
                        >
                          ✓ {s}
                        </span>
                      ))}
                      {m.breakdown.matching_must.length > 4 && (
                        <span className="text-[10px] text-gray-400">
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
                      className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-blue-50 hover:bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 disabled:opacity-50"
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
