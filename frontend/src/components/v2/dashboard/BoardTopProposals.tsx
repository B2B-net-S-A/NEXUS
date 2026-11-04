"use client";

/**
 * „Najlepsze propozycje z bazy” w „Czeka na Ciebie” (07.10.2026).
 *
 * Nocny przegląd bazy publikuje od 07.10 wszystkie osoby powyżej progu, a do
 * skrzynki „Propozycje z bazy” prawie nikt nie zaglądał. Panel pokazuje po
 * kilka najlepszych otwartych propozycji w rekrutacjach, w których osoba jest
 * Rekruterem (serwer: `board_flow._top_proposals`), z dwiema akcjami
 * istniejącymi trasami skrzynki:
 *  - „Dodaj” — `POST /api/jobs/{id}/proposals/bulk` ze źródłem `proposal_inbox`
 *    (domyślny etap rekrutacji, jak „Dodaj do Nowych” w oknie),
 *  - „Pomiń” — z powodem (`DismissReasonDialog`), jak w skrzynce.
 * Obsłużona osoba znika od razu; odświeżenie kolejki dogania w tle.
 */

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { DismissReasonDialog } from "@/components/v2/recruitment/DismissReasonDialog";
import { apiErrorMessage } from "@/lib/api-error";
import { BOARD_TASKS_QUERY_KEY, type FlowJobProposals, type FlowProposalPerson } from "@/lib/api/boardTasks";
import { assignErrorMessage } from "@/lib/assign-error";
import { proposalsBulkApi } from "@/lib/candidate-search-api";
import { jobProposalsApi, jobProposalsKeys } from "@/lib/job-proposals-api";
import { countPl } from "@/lib/plural-pl";
import type { DismissFeedback } from "@/lib/proposal-dismiss";
import { httpStatusFromError } from "@/lib/view-state";

import { Section } from "./BoardTasksSection";

type PersonKey = `${number}-${number}`;

function personKey(jobId: number, candidateId: number): PersonKey {
  return `${jobId}-${candidateId}`;
}

function jobLabel(row: FlowJobProposals): string {
  return row.job_working_title?.trim() || row.job_title;
}

/** Adres okna „Kandydaci do dodania” na zakładce „Propozycje z bazy”. */
export function baseProposalsHref(jobId: number): string {
  return `/jobs/${jobId}?win=add&wintab=base`;
}

/** Ile osób stoi w sekcji (po ukryciu obsłużonych). */
export function topProposalsCount(rows: readonly FlowJobProposals[] | null | undefined): number {
  return (rows ?? []).reduce((n, row) => n + row.people.length, 0);
}

/** Wiersze bez osób już obsłużonych w tej sesji; rekrutacja bez osób znika. */
export function withoutHandled(
  rows: readonly FlowJobProposals[],
  handled: ReadonlySet<string>,
): FlowJobProposals[] {
  return rows
    .map((row) => ({
      ...row,
      people: row.people.filter((p) => !handled.has(personKey(row.job_id, p.candidate_id))),
    }))
    .filter((row) => row.people.length > 0);
}

function formatScore(score: number | null | undefined): string | null {
  return typeof score === "number" && Number.isFinite(score) ? `${Math.round(score)} pkt` : null;
}

export function BoardTopProposals({
  rows,
  expanded,
  onToggle,
  shown,
}: {
  rows: FlowJobProposals[] | null | undefined;
  expanded: boolean;
  onToggle: () => void;
  shown: <T>(kind: string, rows: T[]) => T[];
}) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [handled, setHandled] = useState<ReadonlySet<string>>(new Set());
  const [dismissing, setDismissing] = useState<{ jobId: number; person: FlowProposalPerson } | null>(null);

  const markHandled = (jobId: number, candidateId: number) =>
    setHandled((prev) => new Set([...prev, personKey(jobId, candidateId)]));
  const refresh = (jobId: number) => {
    void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.all(jobId) });
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
  };

  const add = useMutation({
    mutationFn: ({ jobId, candidateId }: { jobId: number; candidateId: number }) =>
      proposalsBulkApi.add(jobId, { candidate_ids: [candidateId], source: "proposal_inbox" }),
    onSuccess: (response, { jobId, candidateId }) => {
      const skipped = response.skipped.find((s) => s.candidate_id === candidateId);
      if (response.added.includes(candidateId) || skipped?.reason === "already_in_job") {
        markHandled(jobId, candidateId);
      }
      if (response.added.includes(candidateId)) showSuccess("Dodano do rekrutacji.");
      else showError(skipped?.reason_label || "Nie dodano tej osoby do rekrutacji.");
      refresh(jobId);
    },
    onError: (error) => showError(assignErrorMessage(error)),
  });

  const dismiss = useMutation({
    mutationFn: async ({
      jobId,
      candidateId,
      feedback,
    }: {
      jobId: number;
      candidateId: number;
      feedback: DismissFeedback;
    }) => {
      try {
        await jobProposalsApi.dismiss(jobId, candidateId, "full_base", feedback);
      } catch (error) {
        // 404 = kandydat zniknął; 409 = ktoś z zespołu właśnie go dodał —
        // w obu przypadkach osoba i tak ma zniknąć z listy.
        const status = httpStatusFromError(error);
        if (status !== 404 && status !== 409) throw error;
      }
    },
    onSuccess: (_data, { jobId, candidateId }) => {
      markHandled(jobId, candidateId);
      showSuccess("Pominięto — wróci tylko z nową wersją CV.");
      refresh(jobId);
    },
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się pominąć propozycji.")),
  });

  const visible = withoutHandled(rows ?? [], handled);
  if (visible.length === 0) return null;
  const busy = add.isPending || dismiss.isPending;

  return (
    <>
      <Section
        title="Najlepsze propozycje z bazy"
        hint="Nocny przegląd bazy wybrał te osoby do Twoich rekrutacji — dodaj do Nowych albo pomiń z powodem."
        count={topProposalsCount(visible)}
        rows={visible.length}
        expanded={expanded}
        onToggle={onToggle}
      >
        {shown("flow_top_proposals", visible).map((row) => (
          <li key={row.job_id} className="px-3 py-2">
            <div className="flex items-baseline gap-2">
              <Link
                href={baseProposalsHref(row.job_id)}
                className="min-w-0 flex-1 truncate text-sm font-medium hover:underline"
              >
                {jobLabel(row)}
              </Link>
              <Link
                href={baseProposalsHref(row.job_id)}
                className="shrink-0 text-xs text-primary hover:underline"
              >
                {`Wszystkie: ${row.total}`}
              </Link>
            </div>
            {row.client_name ? (
              <p className="truncate text-xs text-muted-foreground">{row.client_name}</p>
            ) : null}
            <ul className="mt-1.5 flex flex-col gap-1">
              {row.people.map((person) => {
                const score = formatScore(person.score);
                return (
                  <li
                    key={person.candidate_id}
                    className="flex flex-wrap items-center gap-x-2 gap-y-1"
                  >
                    <Link
                      href={`/candidates/${person.candidate_id}`}
                      className="min-w-[8rem] flex-1 truncate text-sm hover:underline"
                    >
                      {person.candidate_name}
                    </Link>
                    {score ? (
                      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{score}</span>
                    ) : null}
                    <div className="flex shrink-0 items-center gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        aria-label={`Dodaj ${person.candidate_name} do rekrutacji ${jobLabel(row)}`}
                        onClick={() => add.mutate({ jobId: row.job_id, candidateId: person.candidate_id })}
                      >
                        Dodaj
                      </Button>
                      <Button
                        size="sm"
                        variant="quiet"
                        disabled={busy}
                        aria-label={`Pomiń ${person.candidate_name}`}
                        onClick={() => setDismissing({ jobId: row.job_id, person })}
                      >
                        Pomiń
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
            {row.total > row.people.length ? (
              <p className="mt-1 text-xs text-muted-foreground">
                {`i ${countPl(row.total - row.people.length, "kolejna osoba", "kolejne osoby", "kolejnych osób")} w skrzynce`}
              </p>
            ) : null}
          </li>
        ))}
      </Section>
      <DismissReasonDialog
        open={dismissing !== null}
        count={1}
        onOpenChange={(open) => {
          if (!open) setDismissing(null);
        }}
        onConfirm={(feedback) => {
          if (dismissing) {
            dismiss.mutate({
              jobId: dismissing.jobId,
              candidateId: dismissing.person.candidate_id,
              feedback,
            });
          }
          setDismissing(null);
        }}
      />
    </>
  );
}
