"use client";

import {
  PREP_LEVEL_LABELS,
  isReviewV2,
  usePrep,
  type Prep,
} from "@/lib/api/prepMeetings";
import { cn } from "@/lib/utils";

import type { PrepReviewTab } from "./PrepReviewDialog";
import { FollowupNote } from "./PrepReviewTabs";

/**
 * Wynik prepu wprost w kroku karty osoby (Kalendarz → Rozmowy u klienta,
 * makiety 1h38jS5LMc1673CENvUejR, plansza 2): poziom, tematy prowadzącego,
 * odpowiedzi kandydata, dwa zdania podsumowania i wejścia do pełnej oceny
 * oraz transkryptu. Ocena sprzed v2 pokazuje sam poziom i link.
 */

const LEVEL_CLASS: Record<"weak" | "ok" | "good", string> = {
  weak: "bg-destructive/10 text-destructive",
  ok: "bg-muted text-foreground",
  good: "bg-success-muted text-success-muted-foreground",
};

function counts(prep: Prep) {
  const c = prep.review?.criteria ?? {};
  const topics = c.topics ?? [];
  const graded = (c.answers ?? []).filter((a) => a.kind === "must" || a.kind === "question");
  return {
    topicsDone: topics.filter((t) => t.status === "covered").length,
    topicsAll: topics.length,
    strong: graded.filter((a) => a.grade === "strong").length,
    general: graded.filter((a) => a.grade === "general").length,
    weak: graded.filter((a) => a.grade === "weak").length,
    graded: graded.length,
  };
}

export function PrepStepReview({
  eventId,
  onOpen,
}: {
  eventId: number;
  onOpen: (tab: PrepReviewTab) => void;
}) {
  const query = usePrep(eventId);
  const prep = query.data;
  if (query.isPending) {
    return <p className="mt-1 text-xs text-muted-foreground">Ładowanie oceny…</p>;
  }
  if (query.isError || !prep) {
    return (
      <button type="button" onClick={() => onOpen("score")} className="mt-0.5 text-xs font-semibold text-primary hover:underline">
        Zobacz ocenę i transkrypt
      </button>
    );
  }
  const review = prep.review;
  const hasTranscript = prep.transcript_status === "fetched";
  const v2 = isReviewV2(review);
  const n = counts(prep);
  const compared = review?.criteria.comparison ?? [];
  const improved = compared.filter((r) => r.after === "strong").length;

  return (
    <div className="mt-2 flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="prep-step-review">
      <div className="flex flex-wrap gap-1.5 text-[11px] font-semibold">
        <span className="rounded bg-success-muted px-1.5 py-0.5 text-success-muted-foreground">Nagranie ✓</span>
        <span
          className={cn(
            "rounded px-1.5 py-0.5",
            hasTranscript ? "bg-success-muted text-success-muted-foreground" : "bg-muted text-muted-foreground",
          )}
        >
          {hasTranscript ? "Transkrypt ✓" : "Transkrypt — czeka"}
        </span>
        <span
          className={cn(
            "rounded px-1.5 py-0.5",
            review?.status === "ok" ? "bg-success-muted text-success-muted-foreground" : "bg-muted text-muted-foreground",
          )}
        >
          {review?.status === "ok" ? "Ocena ✓" : review ? "Ocena niedostępna" : "Ocena — liczy się"}
        </span>
      </div>

      {review?.status === "ok" && review.level ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className={cn("rounded-md px-2 py-1 text-sm font-bold", LEVEL_CLASS[review.level])}>
            {PREP_LEVEL_LABELS[review.level]}
            {v2 && review.criteria.total != null ? ` · ${review.criteria.total}%` : ""}
          </span>
          {v2 ? (
            <div className="min-w-0 text-xs leading-snug text-foreground">
              {n.topicsAll > 0 ? (
                <div>
                  <span className="font-semibold">Prowadzący:</span> {n.topicsDone} z {n.topicsAll} tematów
                </div>
              ) : null}
              {n.graded > 0 ? (
                <div>
                  <span className="font-semibold">Kandydat:</span> {n.strong} mocne · {n.general} ogólne · {n.weak} słabe
                </div>
              ) : null}
              {compared.length > 0 ? (
                <div>
                  <span className="font-semibold">Z Prepu 1:</span> {improved} z {compared.length} poprawione
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      {review?.summary ? <p className="line-clamp-2 text-xs text-muted-foreground">{review.summary}</p> : null}

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs font-semibold">
        <button type="button" onClick={() => onOpen("score")} className="text-primary hover:underline">
          Pełna ocena
        </button>
        {v2 ? (
          <button type="button" onClick={() => onOpen("summary")} className="text-primary hover:underline">
            Podsumowanie i follow-up
          </button>
        ) : null}
        {hasTranscript ? (
          <button type="button" onClick={() => onOpen("transcript")} className="text-primary hover:underline">
            Transkrypt
          </button>
        ) : null}
      </div>
    </div>
  );
}

/** Krok Prep 2, zanim się odbył: co rekruter ma powtórzyć (z oceny Prepu 1). */
export function Prep2FollowupFromPrep1({ prep1EventId }: { prep1EventId: number }) {
  const query = usePrep(prep1EventId);
  const prep = query.data;
  if (!prep || !isReviewV2(prep.review)) return null;
  return (
    <div className="mt-2 text-sm" data-testid="prep2-followup">
      <FollowupNote prep={prep} compact />
      <p className="mt-1 text-xs text-muted-foreground">
        Lista powstała z oceny Prepu 1. Te punkty AI sprawdzi na Prepie 2.
      </p>
    </div>
  );
}
