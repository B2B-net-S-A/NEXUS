"use client";

/**
 * ChampionCard (Phase 10).
 *
 * Read-only widget rendered on the candidate profile (rekrutacje tab) next to
 * each CandidateStage that has screening answers. Shows the DL's Champion
 * questions alongside the recruiter's responses — a client-ready briefing.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Copy,
  ExternalLink,
  Loader2,
  Share2,
  Sparkles,
} from "lucide-react";
import { screeningApi, type ScreeningQuestion } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ChampionCardProps {
  stageId: number;
  /** Optional override for heading — defaults to "Profil Championa". */
  title?: string;
}

const FIT_LABEL: Record<string, { label: string; color: string }> = {
  fit: { label: "Pasuje", color: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  uncertain: { label: "Niepewnie", color: "bg-amber-100 text-amber-800 border-amber-200" },
  miss: { label: "Nie pasuje", color: "bg-red-100 text-red-700 border-red-200" },
};

export function ChampionCard({ stageId, title = "Profil Championa" }: ChampionCardProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["stage-screening", stageId],
    queryFn: () => screeningApi.getForStage(stageId).then((r) => r.data),
  });

  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const shareMut = useMutation({
    mutationFn: () => screeningApi.createShareToken(stageId, 30),
    onSuccess: (res) => {
      const origin =
        typeof window !== "undefined" ? window.location.origin : "";
      setShareUrl(origin + res.data.share_url_suffix);
    },
  });

  const copyToClipboard = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      /* ignore */
    }
  };

  if (isLoading)
    return (
      <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4 bg-white dark:bg-gray-800 flex items-center gap-2 text-sm text-gray-400">
        <Loader2 className="w-4 h-4 animate-spin" /> Ładuję screening…
      </div>
    );

  if (error) return null;
  if (!data) return null;

  const questions: ScreeningQuestion[] =
    (data.champion_profile as { screening_questions?: ScreeningQuestion[] })
      ?.screening_questions ?? [];
  const answers = data.screening_answers;

  // No Champion Profile configured for this job → nothing to show.
  if (questions.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-200 dark:border-gray-700 p-3 bg-white dark:bg-gray-800 text-xs text-gray-400">
        Delivery Lead nie skonfigurował jeszcze Profilu Championa dla tej
        rekrutacji.
      </div>
    );
  }

  // Profile exists but not screened yet.
  if (!answers) {
    return (
      <div className="rounded-lg border border-amber-200 p-3 bg-amber-50 text-xs text-amber-800 flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
        <div>
          <p className="font-semibold mb-0.5">Screening Championa: brak</p>
          <p>
            Przed rekomendacją do klienta wypełnij pytania screeningowe ({questions.length})
            przypisane przez Delivery Leada.
          </p>
        </div>
      </div>
    );
  }

  const fit = FIT_LABEL[answers.overall_fit] ?? FIT_LABEL.uncertain;
  const hasDealBreaker = answers.answers.some((a) => a.deal_breaker_hit);
  const answered = answers.answers.filter((a) => (a.response ?? "").trim()).length;

  return (
    <div className="rounded-lg border border-purple-200 dark:border-purple-800/40 bg-purple-50/30 dark:bg-purple-900/10 p-3 space-y-2">
      <header className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-sm font-semibold text-purple-800 dark:text-purple-200 flex items-center gap-1.5">
          <Sparkles className="w-4 h-4" /> {title}
        </h3>
        <div className="flex items-center gap-1.5 text-[11px]">
          <span
            className={cn(
              "px-1.5 py-0.5 rounded-md border font-medium",
              fit.color
            )}
          >
            {fit.label}
          </span>
          <span className="text-gray-500">
            {answered}/{answers.answers.length}
          </span>
          {hasDealBreaker && (
            <span className="px-1.5 py-0.5 rounded-md border bg-red-100 text-red-700 border-red-200 font-medium inline-flex items-center gap-0.5">
              <AlertTriangle className="w-3 h-3" />
              deal-breaker
            </span>
          )}
          {!shareUrl ? (
            <button
              type="button"
              onClick={() => shareMut.mutate()}
              disabled={shareMut.isPending}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border border-purple-300 text-purple-700 hover:bg-purple-100 bg-white dark:bg-gray-900 font-medium"
              data-testid="share-champion-card"
              title="Utwórz link do udostępnienia klientowi (ważny 30 dni)"
            >
              <Share2 className="w-3 h-3" />
              {shareMut.isPending ? "…" : "Udostępnij"}
            </button>
          ) : (
            <span className="inline-flex items-center gap-1">
              <button
                type="button"
                onClick={copyToClipboard}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border border-blue-300 text-blue-700 hover:bg-blue-100 bg-white dark:bg-gray-900 font-medium"
                title={shareUrl}
              >
                {copied ? (
                  <>
                    <Check className="w-3 h-3" /> Skopiowano
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3" /> Kopiuj link
                  </>
                )}
              </button>
              <a
                href={shareUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50 bg-white dark:bg-gray-900"
                title="Otwórz podgląd"
              >
                <ExternalLink className="w-3 h-3" />
              </a>
            </span>
          )}
        </div>
      </header>

      <ul className="space-y-1.5">
        {questions.map((q, i) => {
          const a = answers.answers.find((x) => x.question_id === q.id);
          return (
            <li
              key={q.id}
              className="rounded-md bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-2"
            >
              <div className="flex items-start gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-mono mt-0.5">
                  Q{i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-gray-800 dark:text-gray-100">
                    {q.question}
                  </p>
                  <p
                    className={cn(
                      "text-xs mt-1",
                      a?.deal_breaker_hit
                        ? "text-red-700 font-medium"
                        : "text-gray-700 dark:text-gray-200"
                    )}
                  >
                    {a?.response?.trim() || (
                      <span className="italic text-gray-400">brak odpowiedzi</span>
                    )}
                    {a?.deal_breaker_hit && (
                      <span className="ml-2 text-[10px] px-1 py-0.5 rounded bg-red-100 text-red-700 border border-red-200">
                        deal-breaker ✗
                      </span>
                    )}
                  </p>
                </div>
                {a && !a.deal_breaker_hit && (a.response ?? "").trim() && (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0 mt-0.5" />
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {answers.notes && (
        <p className="text-[11px] text-gray-600 dark:text-gray-400 italic border-t border-gray-200 dark:border-gray-700 pt-2">
          {answers.notes}
        </p>
      )}
    </div>
  );
}
