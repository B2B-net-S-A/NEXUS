"use client";

/**
 * Pierwsza kolumna Tablicy — „Do przejrzenia" (decyzja Artura 22.09.2026).
 *
 * Jedna kolumna zbiera wszystkich, których trzeba przejrzeć: przepięcia
 * (osoby wysłane już do klienta przy podobnym requeście), propozycje z bazy
 * i — niżej, w tej samej kolumnie — osoby z ogłoszeń (etap „Ogłoszenia").
 * ✓ przenosi osobę do „Screening", ✕ ją pomija. „Nowi" to już tylko osoby
 * dodane ręcznie.
 *
 * Lista to TA SAMA scalona lista co segment „Propozycje z bazy" w Tabeli
 * (`useJobProposals`: skrzynka + przegląd bazy + podobne projekty +
 * rekomendacje). Pierwsza wersja czytała samą skrzynkę i na produkcji
 * pokazywała „0 — nikt nie czeka" obok „20 propozycji z bazy" w Tabeli.
 */

import Link from "next/link";
import { Check, X } from "lucide-react";

import { jobProposalsHref } from "@/components/v2/jobs/JobListCells";
import { PROPOSAL_SOURCE_LABEL } from "@/components/v2/recruitment/types";
import { useJobProposals } from "@/components/v2/recruitment/useJobProposals";
import { DEFAULT_PROPOSAL_FILTERS } from "@/lib/proposals-merge";
import { cn } from "@/lib/utils";

export const BOARD_REVIEW_LIMIT = 6;

export function BoardReviewSection({
  jobId,
  readOnly,
  showPostingHeading = true,
  pipelineCandidateIds,
  budgetHourly = null,
}: {
  jobId: number;
  readOnly: boolean;
  /** Podpis „Z ogłoszeń" nad kartami etapu „Ogłoszenia" tej samej kolumny. */
  showPostingHeading?: boolean;
  /** Osoby już w rekrutacji (z tablicy) — bez nich hook pyta osobno. */
  pipelineCandidateIds?: readonly number[];
  budgetHourly?: number | null;
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
  const loading = status.inbox.isLoading;

  return (
    <div className="space-y-1.5 border-b border-border p-2" data-testid="board-review">
      <div className="flex items-center justify-between px-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>Z bazy i przepięcia</span>
        {!loading ? <span className="tabular-nums">{total}</span> : null}
      </div>
      {status.inbox.isError ? (
        <p className="px-1 text-xs text-destructive">
          Nie wczytano propozycji.{" "}
          <button type="button" className="underline" onClick={status.retryEngine}>
            Ponów
          </button>
        </p>
      ) : loading ? (
        <p className="px-1 text-xs text-muted-foreground">Wczytuję…</p>
      ) : shown.length === 0 ? (
        <p className="px-1 text-xs text-muted-foreground">Nikt nie czeka na przejrzenie.</p>
      ) : (
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
                      proposals.addToJob([row.candidateId], { initialStageLegacy: "screening" })
                    }
                    disabled={busy}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] font-medium hover:bg-primary/10 hover:text-primary disabled:opacity-50"
                    aria-label={`Dodaj ${row.fullName} do Screening`}
                  >
                    <Check className="h-3 w-3" aria-hidden="true" /> Screening
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
      {total > shown.length ? (
        <Link
          href={jobProposalsHref(jobId)}
          className="block px-1 text-xs font-semibold text-primary hover:underline"
        >
          Przejrzyj wszystkich {total} →
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
