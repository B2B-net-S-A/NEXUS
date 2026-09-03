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
import type { EmploymentInfo } from "@/components/v2/CandidateHighlights";

interface ChampionCardProps {
  stageId: number;
  /** Optional override for heading — defaults to "Profil Championa". */
  title?: string;
  /**
   * When the candidate is currently employed at one of our clients, the
   * widget shows a warning above the "Share" button so the recruiter pauses
   * before sending the profile externally.
   */
  employment?: EmploymentInfo;
  readOnly?: boolean;
}

const FIT_LABEL: Record<string, { label: string; color: string }> = {
  fit: { label: "Pasuje", color: "bg-emerald-100 text-emerald-700 border-emerald-200" },
  uncertain: { label: "Niepewnie", color: "bg-amber-100 text-amber-800 border-amber-200" },
  miss: { label: "Nie pasuje", color: "bg-destructive/15 text-destructive border-destructive/20" },
};

export function ChampionCard({
  stageId,
  title = "Profil Championa",
  employment,
  readOnly = false,
}: ChampionCardProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["stage-screening", stageId],
    queryFn: () => screeningApi.getForStage(stageId).then((r) => r.data),
  });

  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const shareMut = useMutation({
    mutationFn: () => {
      if (readOnly) throw new Error("Brak prawa zapisu w Sourcing");
      return screeningApi.createShareToken(stageId, 30);
    },
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
      <div className="rounded-lg border border-border dark:border-border p-4 bg-card dark:bg-muted flex items-center gap-2 text-sm text-muted-foreground">
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
      <div className="rounded-lg border border-dashed border-border dark:border-border p-3 bg-card dark:bg-muted text-xs text-muted-foreground">
        Delivery Lead nie skonfigurował jeszcze Profilu Championa dla tej
        rekrutacji.
      </div>
    );
  }

  // Profile exists but not screened yet.
  if (!answers) {
    return (
      <div className="rounded-lg border border-amber-200 p-3 bg-amber-50 text-xs text-amber-800 flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
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
          <span className="text-muted-foreground">
            {answered}/{answers.answers.length}
          </span>
          {hasDealBreaker && (
            <span className="px-1.5 py-0.5 rounded-md border bg-destructive/15 text-destructive border-destructive/20 font-medium inline-flex items-center gap-0.5">
              <AlertTriangle className="w-3 h-3" />
              deal-breaker
            </span>
          )}
          {!readOnly ? (
            !shareUrl ? (
            <button
              type="button"
              onClick={() => {
                if (employment?.state === "employed_at_client") {
                  const clientLabel = employment.client_name
                    ? ` (${employment.client_name})`
                    : "";
                  const ok = window.confirm(
                    `Uwaga: konsultant jest obecnie zatrudniony u naszego klienta${clientLabel}. ` +
                      "Tworzysz link share — upewnij się, że nie wysyłasz go do tego samego klienta. Kontynuować ? "
                  );
                  if (!ok) return;
                }
                shareMut.mutate();
              }}
              disabled={shareMut.isPending}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border border-purple-300 text-purple-700 hover:bg-purple-100 bg-card dark:bg-card font-medium"
              data-testid="share-champion-card"
              title={
                employment?.state === "employed_at_client"
                  ? `Ostrzeżenie: konsultant u klienta ${employment.client_name ?? ""}`
                  : "Utwórz link do udostępnienia klientowi (ważny 30 dni)"
              }
            >
              <Share2 className="w-3 h-3" />
              {shareMut.isPending ? "…" : "Udostępnij"}
            </button>
          ) : (
            <span className="inline-flex items-center gap-1">
              <button
                type="button"
                onClick={copyToClipboard}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border border-primary/30 text-primary hover:bg-primary/15 bg-card dark:bg-card font-medium"
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
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border border-border text-foreground hover:bg-muted bg-card dark:bg-card"
                title="Otwórz podgląd"
              >
                <ExternalLink className="w-3 h-3" />
              </a>
            </span>
            )
          ) : null}
        </div>
      </header>

      <ul className="space-y-1.5">
        {questions.map((q, i) => {
          const a = answers.answers.find((x) => x.question_id === q.id);
          return (
            <li
              key={q.id}
              className="rounded-md bg-card dark:bg-muted border border-border dark:border-border p-2"
            >
              <div className="flex items-start gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 font-mono mt-0.5">
                  Q{i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-foreground dark:text-foreground">
                    {q.question}
                  </p>
                  <p
                    className={cn(
                      "text-xs mt-1",
                      a?.deal_breaker_hit
                        ? "text-destructive font-medium"
                        : "text-foreground dark:text-muted-foreground"
                    )}
                  >
                    {a?.response?.trim() || (
                      <span className="italic text-muted-foreground">brak odpowiedzi</span>
                    )}
                    {a?.deal_breaker_hit && (
                      <span className="ml-2 text-[10px] px-1 py-0.5 rounded bg-destructive/15 text-destructive border border-destructive/20">
                        deal-breaker ✗
                      </span>
                    )}
                  </p>
                </div>
                {a && !a.deal_breaker_hit && (a.response ?? "").trim() && (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0 mt-0.5" />
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {answers.notes && (
        <p className="text-[11px] text-muted-foreground dark:text-muted-foreground italic border-t border-border dark:border-border pt-2">
          {answers.notes}
        </p>
      )}
    </div>
  );
}
