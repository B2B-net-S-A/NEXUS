"use client";

/**
 * ChampionHistoricalMatchesPanel — Phase 15.
 *
 * Shows the DL up to 3 historical closed roles (same-client preferred) whose
 * `champion_profile` is populated, plus aggregated must/nice skill frequency
 * across the sample. The "Zaproponuj na podstawie historii" CTA kicks off the
 * LLM draft via `champion-profile/generate-from-history`, invalidates the
 * parent's pending-suggestions query, and hands the new suggestion up via
 * `onSuggestionGenerated` so the existing review modal opens transparently.
 *
 * Designed to be source-agnostic — the generated draft carries source_type
 * "historical_jobs", which `sourceLabel` in ChampionProfileSourcesPanel
 * already renders.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, Loader2, ShieldCheck, Sparkles, Train } from "lucide-react";
import { championSuggestionsApi } from "@/lib/api";
import type {
  ChampionProfileSuggestion,
  HistoricalMatchPreview,
  HistoricalSkillFrequency,
  SkillFrequencyEntry,
} from "@/lib/api";

interface ChampionHistoricalMatchesPanelProps {
  jobId: number;
  clientId: number | null | undefined;
  onSuggestionGenerated: (suggestion: ChampionProfileSuggestion) => void;
  crossClient: boolean;
  onToggleCrossClient: (value: boolean) => void;
}

const CARD_LIMIT = 3;

export function ChampionHistoricalMatchesPanel({
  jobId,
  clientId,
  onSuggestionGenerated,
  crossClient,
  onToggleCrossClient,
}: ChampionHistoricalMatchesPanelProps) {
  const qc = useQueryClient();

  const preview = useQuery({
    queryKey: ["champion-historical-matches", jobId, crossClient],
    queryFn: async () => {
      const res = await championSuggestionsApi.fetchHistoricalMatches(jobId, {
        topK: 5,
        crossClient,
      });
      return res.data;
    },
    // Preview endpoint is cheap but not free (Voyage embed). Avoid refetching
    // on window focus — DL usually scrolls past once.
    refetchOnWindowFocus: false,
    enabled: clientId != null || crossClient,
  });

  const generateMutation = useMutation({
    mutationFn: async () => {
      const res = await championSuggestionsApi.generateFromHistory(jobId, {
        topK: 5,
        crossClient,
      });
      return res.data;
    },
    onSuccess: (suggestion) => {
      qc.invalidateQueries({ queryKey: ["champion-suggestions", jobId] });
      onSuggestionGenerated(suggestion);
    },
  });

  const matches = (preview.data?.matches ?? []).slice(0, CARD_LIMIT);
  const freq = preview.data?.skill_frequency;
  const hasMatches = matches.length > 0;
  const canGenerate = matches.length >= 2 && !generateMutation.isPending;

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-gray-500 font-semibold">
            Podobne role z przeszłości
          </div>
          <div className="text-xs text-gray-500">
            Pre-fill Profilu Championa na podstawie zamkniętych ról tego klienta.
          </div>
        </div>
        <label className="text-xs text-gray-600 dark:text-gray-400 inline-flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={crossClient}
            onChange={(e) => onToggleCrossClient(e.target.checked)}
            className="accent-purple-600"
          />
          Wszyscy klienci
        </label>
      </div>

      {preview.isLoading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader2 className="w-4 h-4 animate-spin" />
          Szukam podobnych ról…
        </div>
      )}

      {preview.isError && (
        <div className="text-sm text-red-600 dark:text-red-400">
          Nie udało się pobrać podobnych ról. Spróbuj ponownie za chwilę.
        </div>
      )}

      {!preview.isLoading && !preview.isError && !hasMatches && (
        <div className="text-sm italic text-gray-400">
          Brak zamkniętych ról z Profilem Championa do porównania
          {crossClient ? "" : " u tego klienta"}.
          {!crossClient && (
            <>
              {" "}
              <button
                type="button"
                onClick={() => onToggleCrossClient(true)}
                className="underline text-purple-600"
              >
                Spróbuj cross-client
              </button>
              .
            </>
          )}
        </div>
      )}

      {hasMatches && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {matches.map((m) => (
              <MatchCard key={m.job_id} match={m} />
            ))}
          </div>

          {freq && freq.n > 0 && (
            <SkillFrequencyRow frequency={freq} />
          )}

          <div className="flex items-center gap-3 pt-1">
            <button
              type="button"
              onClick={() => generateMutation.mutate()}
              disabled={!canGenerate}
              className="px-4 py-2 text-sm rounded-lg bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {generateMutation.isPending ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Sparkles className="w-4 h-4" />
              )}
              Zaproponuj na podstawie historii
            </button>
            {matches.length < 2 && (
              <span className="text-xs text-gray-500 italic">
                Wymagane min. 2 matches — znalezione: {matches.length}
              </span>
            )}
          </div>

          {generateMutation.isError && (
            <div className="text-sm text-red-600 dark:text-red-400">
              Generowanie nie powiodło się. Spróbuj ponownie lub włącz
              cross-client.
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function MatchCard({ match }: { match: HistoricalMatchPreview }) {
  const similarityPct = Math.round(match.similarity * 100);
  const similarityTone =
    similarityPct >= 85
      ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
      : similarityPct >= 70
      ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300"
      : "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300";

  return (
    <div className="border border-gray-200 dark:border-gray-800 rounded-lg p-3 space-y-2 bg-white dark:bg-gray-900">
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm font-medium text-gray-900 dark:text-gray-100 leading-snug line-clamp-2">
          {match.title}
        </div>
        <span
          className={`text-xs font-semibold px-1.5 py-0.5 rounded ${similarityTone} shrink-0`}
        >
          {similarityPct}%
        </span>
      </div>

      <div className="text-xs text-gray-500 space-y-1">
        {match.client_name && <div>{match.client_name}</div>}
        {match.closed_at && (
          <div className="inline-flex items-center gap-1">
            <Clock3 className="w-3 h-3" />
            Zamknięte{" "}
            {new Date(match.closed_at).toLocaleDateString("pl-PL", {
              year: "numeric",
              month: "short",
            })}
          </div>
        )}
        {match.seniority && (
          <div className="uppercase tracking-wide">{match.seniority}</div>
        )}
      </div>

      <div className="flex flex-wrap gap-1">
        {match.same_train && (
          <Badge tone="purple" icon={<Train className="w-3 h-3" />}>
            ten sam train
          </Badge>
        )}
        {match.has_champion_profile && (
          <Badge tone="green" icon={<ShieldCheck className="w-3 h-3" />}>
            ma profil
          </Badge>
        )}
        {match.must_skills_count > 0 && (
          <Badge tone="gray">{match.must_skills_count} must-have</Badge>
        )}
      </div>
    </div>
  );
}

function SkillFrequencyRow({
  frequency,
}: {
  frequency: HistoricalSkillFrequency;
}) {
  const topMust = frequency.must.slice(0, 8);
  if (topMust.length === 0) return null;
  return (
    <div className="rounded-lg bg-gray-50 dark:bg-gray-900/40 border border-gray-200 dark:border-gray-800 px-3 py-2 space-y-1">
      <div className="text-xs uppercase tracking-wide text-gray-500 font-semibold">
        Powtarzalne must-have (próba: {frequency.n})
      </div>
      <div className="flex flex-wrap gap-1.5">
        {topMust.map((s) => (
          <SkillChip key={s.name} entry={s} threshold={frequency.threshold} />
        ))}
      </div>
    </div>
  );
}

function SkillChip({
  entry,
  threshold,
}: {
  entry: SkillFrequencyEntry;
  threshold: number;
}) {
  const highlighted = entry.fraction >= threshold;
  const cls = highlighted
    ? "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-200 border-purple-300 dark:border-purple-800"
    : "bg-white dark:bg-gray-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-800";
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full border inline-flex items-center gap-1 ${cls}`}
      title={`${entry.count} z ${Math.round(entry.count / Math.max(entry.fraction, 0.0001))} — ${Math.round(entry.fraction * 100)}%`}
    >
      <span className="font-medium">{entry.name}</span>
      <span className="opacity-60">
        {entry.count}/
        {Math.max(Math.round(entry.count / Math.max(entry.fraction, 0.0001)), entry.count)}
      </span>
    </span>
  );
}

type BadgeTone = "purple" | "green" | "gray";

function Badge({
  tone,
  icon,
  children,
}: {
  tone: BadgeTone;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  const classes: Record<BadgeTone, string> = {
    purple:
      "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-200",
    green:
      "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
    gray:
      "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300",
  };
  return (
    <span
      className={`text-xs px-1.5 py-0.5 rounded inline-flex items-center gap-1 ${classes[tone]}`}
    >
      {icon}
      {children}
    </span>
  );
}
