"use client";

/**
 * Propozycje na górze kolumny „Nowi" (Tablica 6 kolumn, decyzja Artura
 * 23.09.2026; do 22.09 osobna kolumna „Do przejrzenia").
 *
 * Przepięcia (osoby wysłane już do klienta przy podobnym requeście) i
 * propozycje z bazy. „Biorę" dodaje osobę do „Nowych" z blokadą 12 h na
 * klikającego (serwer: `candidate_claim`), ✕ ją pomija. Osoby z ogłoszeń
 * są zwykłymi kartami tej kolumny z odznaką „Z ogłoszenia".
 *
 * Lista to TA SAMA scalona lista co segment „Propozycje z bazy" w Tabeli
 * (`useJobProposals`: skrzynka + przegląd bazy + podobne projekty +
 * rekomendacje). Pierwsza wersja czytała samą skrzynkę i na produkcji
 * pokazywała „0 — nikt nie czeka" obok „20 propozycji z bazy" w Tabeli.
 */

import { useEffect } from "react";
import Link from "next/link";
import { Check, Sparkles, X } from "lucide-react";

import { jobProposalsHref } from "@/components/v2/jobs/JobListCells";
import { PROPOSAL_SOURCE_LABEL } from "@/components/v2/recruitment/types";
import { useJobProposals } from "@/components/v2/recruitment/useJobProposals";
import { boardReviewCountLabel, boardReviewState } from "@/lib/board-review-state";
import { DEFAULT_PROPOSAL_FILTERS } from "@/lib/proposals-merge";
import { cn } from "@/lib/utils";

// 3, nie 6 (test na produkcji 23.09.2026): przy kilkudziesięciu przepięciach
// sześć kart propozycji spychało prawdziwych „Nowych" pod ekran. Resztę
// otwiera „Przejrzyj wszystkich N".
export const BOARD_REVIEW_LIMIT = 3;

export function BoardReviewSection({
  jobId,
  readOnly,
  showPostingHeading = true,
  pipelineCandidateIds,
  budgetHourly = null,
  onTotalChange,
  compact = false,
  onOpenPanel,
}: {
  jobId: number;
  readOnly: boolean;
  /** Podpis „Z ogłoszeń" nad kartami etapu „Ogłoszenia" tej samej kolumny. */
  showPostingHeading?: boolean;
  /** Osoby już w rekrutacji (z tablicy) — bez nich hook pyta osobno. */
  pipelineCandidateIds?: readonly number[];
  budgetHourly?: number | null;
  /** Ile propozycji czeka — nagłówek kolumny „Do przejrzenia" liczy je razem
   *  z kartami etapu „Ogłoszenia". `null` = jeszcze nie wiadomo. */
  onTotalChange?: (total: number | null) => void;
  /**
   * Rekrutacja v5 (makiety CG4mBk9x…, zakładka 1): zamiast kart propozycji
   * jedno pole „Propozycje z bazy · N — Przejrzyj" i „Znajdź w bazie (AI)".
   * Dodawanie idzie przez panel „Dodaj kandydatów" (`onOpenPanel`).
   */
  compact?: boolean;
  onOpenPanel?: (tab: "search" | "proposals") => void;
}) {
  const proposals = useJobProposals(jobId, {
    filters: DEFAULT_PROPOSAL_FILTERS,
    budgetHourly,
    pipelineCandidateIds,
    readOnly,
  });
  const { entries, status } = proposals;
  const shown = entries.slice(0, BOARD_REVIEW_LIMIT);
  const total = entries.length;
  const busy = proposals.adding || proposals.dismissing;
  // REC-02: „Nikt nie czeka" dopiero, gdy KAŻDE źródło odpowiedziało; awaria
  // któregokolwiek to komunikat z „Ponów", nie pustka.
  const view = boardReviewState({
    settled: status.settled,
    inboxError: status.inbox.isError,
    similarError: status.similar.isError,
    recommendationsError: status.recommendations.isError,
    runError: Boolean(status.run.error),
    count: total,
  });
  const countLabel = boardReviewCountLabel(total, Boolean(status.inbox.hasMore));
  const failedText = view.failed.join(", ");
  // Nagłówek kolumny dostaje liczbę dopiero, gdy jest pewna: wszystkie
  // źródła odpowiedziały i żadne nie padło (REC-02). `null` = nie wiadomo.
  const known = status.settled && (view.kind === "list" || view.kind === "empty");
  useEffect(() => {
    onTotalChange?.(known ? total : null);
  }, [onTotalChange, known, total]);

  if (compact) {
    return (
      <div
        className="space-y-1.5 border-b border-border p-2"
        data-testid="board-review"
        data-help="jobs.board.review"
      >
        <div className="flex items-center justify-between gap-2 rounded-md border border-dashed border-primary/40 bg-primary/5 px-2 py-1.5 text-xs">
          <span className="min-w-0 font-medium leading-snug text-foreground">
            Propozycje z bazy ·{" "}
            <span className="tabular-nums" data-testid="board-review-count">
              {view.kind === "loading" ? "…" : countLabel}
            </span>
          </span>
          {onOpenPanel ? (
            <button
              type="button"
              onClick={() => onOpenPanel("proposals")}
              className="shrink-0 font-semibold text-primary hover:underline"
            >
              Przejrzyj
            </button>
          ) : (
            <Link href={jobProposalsHref(jobId)} className="shrink-0 font-semibold text-primary hover:underline">
              Przejrzyj
            </Link>
          )}
        </div>
        {view.kind === "error" || view.kind === "partial" ? (
          <p className="px-1 text-xs text-destructive" role="alert">
            {view.kind === "error"
              ? `Nie wczytano propozycji (${failedText}).`
              : `Lista może być niepełna — nie odpowiedziały: ${failedText}.`}{" "}
            <button type="button" className="underline" onClick={status.retryEngine}>
              Ponów
            </button>
          </p>
        ) : null}
        {!readOnly && onOpenPanel ? (
          <button
            type="button"
            onClick={() => onOpenPanel("search")}
            className="inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium text-foreground hover:border-primary/40 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Sparkles className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
            Znajdź w bazie (AI)
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-1.5 border-b border-border p-2" data-testid="board-review" data-help="jobs.board.review">
      <div className="flex items-center justify-between px-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>Propozycje · z bazy i przepięcia</span>
        {view.kind === "list" || view.kind === "empty" || view.kind === "partial" ? (
          <span className="tabular-nums" data-testid="board-review-count">
            {countLabel}
          </span>
        ) : null}
      </div>
      {view.kind === "error" || view.kind === "partial" ? (
        <p className="px-1 text-xs text-destructive" role="alert">
          {view.kind === "error"
            ? `Nie wczytano listy do przejrzenia (${failedText}).`
            : `Lista może być niepełna — nie odpowiedziały: ${failedText}.`}{" "}
          <button
            type="button"
            className="underline"
            onClick={status.retryEngine}
          >
            Ponów
          </button>
        </p>
      ) : null}
      {view.kind === "loading" ? (
        <p className="px-1 text-xs text-muted-foreground">Wczytuję…</p>
      ) : view.kind === "empty" ? (
        <p className="px-1 text-xs text-muted-foreground">Nikt nie czeka na przejrzenie.</p>
      ) : view.kind === "error" ? null : (
        shown.map(({ row, detail }) => {
          const source = row.sources.includes("reassign") ? "reassign" : row.sources[0];
          const label = source ? PROPOSAL_SOURCE_LABEL[source] : null;
          const note = row.reason ?? detail.title;
          return (
            <div
              key={row.candidateId}
              className={cn(
                "rounded-lg border bg-card px-2.5 py-2 text-sm",
                source === "reassign" ? "border-primary/40" : "border-border",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={`/candidates/${row.candidateId}`}
                  className="min-w-0 truncate font-medium text-foreground hover:text-primary hover:underline"
                >
                  {row.fullName}
                </Link>
                {row.fitScore != null ? (
                  <span className="shrink-0 text-xs font-bold tabular-nums text-primary">
                    {Math.round(row.fitScore)}%
                  </span>
                ) : null}
              </div>
              {label ? (
                <span
                  className={cn(
                    "mt-1 inline-block rounded px-1.5 text-[10.5px] font-semibold",
                    source === "reassign"
                      ? "border border-primary/40 bg-primary/5 text-primary"
                      : "bg-muted text-muted-foreground",
                  )}
                >
                  {label}
                </span>
              ) : null}
              {note ? (
                <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">{note}</p>
              ) : null}
              {!readOnly ? (
                <div className="mt-1.5 flex gap-1">
                  <button
                    type="button"
                    onClick={() =>
                      proposals.addToJob([row.candidateId], { initialStageLegacy: "new" })
                    }
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] font-medium hover:bg-primary/10 hover:text-primary disabled:opacity-50"
                    aria-label={`Biorę ${row.fullName} — dodaj do Nowych na 12 h`}
                  >
                    <Check className="h-3 w-3" aria-hidden="true" /> Biorę
                  </button>
                  <button
                    type="button"
                    onClick={() => proposals.dismiss([row.candidateId])}
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-muted disabled:opacity-50"
                    aria-label={`Pomiń ${row.fullName}`}
                  >
                    <X className="h-3 w-3" aria-hidden="true" /> Pomiń
                  </button>
                </div>
              ) : null}
            </div>
          );
        })
      )}
      {view.kind !== "error" && (total > shown.length || status.inbox.hasMore) ? (
        <Link
          href={jobProposalsHref(jobId)}
          className="block px-1 text-xs font-semibold text-primary hover:underline"
        >
          Przejrzyj wszystkich {countLabel} →
        </Link>
      ) : null}
      {showPostingHeading ? (
        <div className="px-1 pt-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Z ogłoszeń
        </div>
      ) : null}
    </div>
  );
}
