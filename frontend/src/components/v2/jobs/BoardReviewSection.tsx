"use client";

/**
 * Pierwsza kolumna Tablicy — „Do przejrzenia" (decyzja Artura 22.09.2026).
 *
 * Jedna kolumna zbiera wszystkich, których trzeba przejrzeć: przepięcia
 * (osoby wysłane już do klienta przy podobnym requeście), propozycje z bazy
 * i — niżej, w tej samej kolumnie — osoby z ogłoszeń (etap „Ogłoszenia").
 * ✓ przenosi osobę do „Screening", ✕ ją pomija. „Nowi" to już tylko osoby
 * dodane ręcznie.
 */

import Link from "next/link";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { jobProposalsHref } from "@/components/v2/jobs/JobListCells";
import {
  PROPOSAL_SOURCE_LABEL,
  type ProposalSource,
} from "@/components/v2/recruitment/types";
import { apiErrorMessage } from "@/lib/api-error";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import {
  jobProposalsApi,
  jobProposalsKeys,
  type ProposalInboxItem,
} from "@/lib/job-proposals-api";
import { reassignReason } from "@/lib/proposals-merge";
import { cn } from "@/lib/utils";

export const BOARD_REVIEW_LIMIT = 6;
export const boardReviewKey = (jobId: number) =>
  jobProposalsKeys.inbox(jobId, BOARD_REVIEW_LIMIT);

function fullName(item: ProposalInboxItem): string {
  const name = [item.candidate.name, item.candidate.lastname].filter(Boolean).join(" ");
  return name || `Kandydat #${item.candidate.id}`;
}

function primarySource(item: ProposalInboxItem): ProposalSource {
  const known = item.sources.filter((s): s is ProposalSource => s in PROPOSAL_SOURCE_LABEL);
  if (known.includes("reassign")) return "reassign";
  return known[0] ?? "full_base";
}

function scoreOf(item: ProposalInboxItem): number | null {
  const value = typeof item.score === "string" ? Number(item.score) : item.score;
  return value != null && Number.isFinite(value) ? Math.round(value) : null;
}

export function BoardReviewSection({
  jobId,
  readOnly,
  showPostingHeading = true,
}: {
  jobId: number;
  readOnly: boolean;
  /** Podpis „Z ogłoszeń" nad kartami etapu „Ogłoszenia" tej samej kolumny. */
  showPostingHeading?: boolean;
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [busy, setBusy] = useState<number | null>(null);
  const inbox = useQuery({
    queryKey: boardReviewKey(jobId),
    queryFn: ({ signal }) =>
      jobProposalsApi.inbox(jobId, { limit: BOARD_REVIEW_LIMIT }, signal),
    staleTime: 30_000,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
    void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
    void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  };

  const add = async (item: ProposalInboxItem) => {
    setBusy(item.candidate.id);
    try {
      const result = await proposalsBulkApi.add(jobId, {
        candidate_ids: [item.candidate.id],
        source: "proposal_inbox",
        initial_stage_legacy: "screening",
        run_id: item.run_id ?? null,
      });
      if (result.total_added > 0) {
        showSuccess(`${fullName(item)} → Screening.`);
      } else {
        showError(
          result.skipped[0]?.reason_label ?? "Nie dodano — ta osoba jest już w rekrutacji.",
        );
      }
      refresh();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się dodać osoby."));
    } finally {
      setBusy(null);
    }
  };

  const dismiss = async (item: ProposalInboxItem) => {
    setBusy(item.candidate.id);
    try {
      await jobProposalsApi.dismiss(jobId, item.candidate.id, primarySource(item));
      refresh();
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pominąć osoby."));
    } finally {
      setBusy(null);
    }
  };

  const items = inbox.data?.items ?? [];
  const total = inbox.data?.total ?? 0;

  return (
    <div className="space-y-1.5 border-b border-border p-2" data-testid="board-review">
      <div className="flex items-center justify-between px-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>Z bazy i przepięcia</span>
        {inbox.isSuccess ? <span className="tabular-nums">{total}</span> : null}
      </div>
      {inbox.isError ? (
        <p className="px-1 text-xs text-destructive">
          Nie wczytano propozycji.{" "}
          <button type="button" className="underline" onClick={() => inbox.refetch()}>
            Ponów
          </button>
        </p>
      ) : inbox.isLoading ? (
        <p className="px-1 text-xs text-muted-foreground">Wczytuję…</p>
      ) : items.length === 0 ? (
        <p className="px-1 text-xs text-muted-foreground">Nikt nie czeka na przejrzenie.</p>
      ) : (
        items.map((item) => {
          const source = primarySource(item);
          const score = scoreOf(item);
          const reassign = item.reassign_from ?? null;
          return (
            <div
              key={item.candidate.id}
              className={cn(
                "rounded-lg border bg-card px-2.5 py-2 text-sm",
                source === "reassign" ? "border-primary/40" : "border-border",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <Link
                  href={`/candidates/${item.candidate.id}`}
                  className="min-w-0 truncate font-medium text-foreground hover:text-primary hover:underline"
                >
                  {fullName(item)}
                </Link>
                {score != null ? (
                  <span className="shrink-0 text-xs font-bold tabular-nums text-primary">
                    {score}%
                  </span>
                ) : null}
              </div>
              <span
                className={cn(
                  "mt-1 inline-block rounded px-1.5 text-[10.5px] font-semibold",
                  source === "reassign"
                    ? "border border-primary/40 bg-primary/5 text-primary"
                    : "bg-muted text-muted-foreground",
                )}
              >
                {PROPOSAL_SOURCE_LABEL[source]}
              </span>
              {reassign ? (
                <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                  {reassignReason(reassign)}
                </p>
              ) : item.candidate.title ? (
                <p className="mt-1 truncate text-[11px] text-muted-foreground">
                  {item.candidate.title}
                </p>
              ) : null}
              {!readOnly ? (
                <div className="mt-1.5 flex gap-1">
                  <button
                    type="button"
                    onClick={() => add(item)}
                    disabled={busy === item.candidate.id}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] font-medium hover:bg-primary/10 hover:text-primary disabled:opacity-50"
                    aria-label={`Dodaj ${fullName(item)} do Screening`}
                  >
                    <Check className="h-3 w-3" aria-hidden="true" /> Screening
                  </button>
                  <button
                    type="button"
                    onClick={() => dismiss(item)}
                    disabled={busy === item.candidate.id}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-muted disabled:opacity-50"
                    aria-label={`Pomiń ${fullName(item)}`}
                  >
                    <X className="h-3 w-3" aria-hidden="true" /> Pomiń
                  </button>
                </div>
              ) : null}
            </div>
          );
        })
      )}
      {total > items.length ? (
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
