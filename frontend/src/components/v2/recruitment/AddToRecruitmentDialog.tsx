"use client";

/**
 * „Dodaj do rekrutacji” dla jednej albo wielu osób — z listy kandydatów
 * (`source="candidate_list"`) i z wyników Talent Radaru (`source="talent_radar"`).
 *
 * Zapis idzie przez to samo API co AI Matching (`POST /api/jobs/{id}/proposals/bulk`),
 * więc pomijanie osób już obecnych w rekrutacji, bramki klienta i telemetria
 * działają tak samo. Rekruter dodaje osoby także do rekrutacji, w których nie
 * jest w zespole (decyzja Artura 07.10.2026) — wybór obejmuje wszystkie otwarte
 * rekrutacje, a odmowę opisuje zdanie z serwera.
 *
 * Okno zostaje otwarte, gdy nikogo nie dodano albo ktoś ma w tej rekrutacji
 * zamkniętą kartę (12.10.2026): pokazuje powód z serwera, a zamkniętą kartę
 * przywraca ruchem karty (`usePipelineMoveCore`) — tym samym co na Tablicy,
 * więc z anulowaniem maila odmowy i oknem „Przenieś mimo to”.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  proposalsBulkApi,
  type BulkAddSource,
  type BulkClosedCard,
  type BulkProposalsResponse,
  type BulkSkippedRow,
} from "@/lib/candidate-search-api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { JobPicker, type JobPickerJob } from "./JobPicker";

export interface AddToRecruitmentResult {
  job: JobPickerJob;
  response: BulkProposalsResponse;
  /** Ile osób wróciło z „Zamkniętych” przyciskiem w oknie (zamiast dodania). */
  restored?: number;
}

interface AddToRecruitmentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateIds: number[];
  source: BulkAddSource;
  /** Przegląd bazy, z którego pochodzi wynik (telemetria). */
  runId?: string | null;
  /** Tekst w opisie okna, np. imię i nazwisko przy jednej osobie. */
  subject?: string;
  /** Wołane, gdy ktoś trafił do rekrutacji — dodany albo przywrócony. */
  onAdded?: (result: AddToRecruitmentResult) => void;
}

export type ClosedRow = BulkSkippedRow & { closed: BulkClosedCard };

function isClosedRow(row: BulkSkippedRow): row is ClosedRow {
  return row.reason === "closed_in_job" && row.closed != null;
}

/** „1 osobę”, „2 osoby”, „5 osób”, „22 osoby” — biernik liczebnika. */
function peopleAccusative(n: number): string {
  if (n === 1) return "osobę";
  const mod10 = n % 10;
  const mod100 = n % 100;
  return mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "osoby" : "osób";
}

function addedSentence(job: JobPickerJob, added: number): string {
  return added === 0
    ? `Nikogo nie dodano do „${job.title}”.`
    : `Dodano ${added} ${peopleAccusative(added)} do „${job.title}”.`;
}

export function addToRecruitmentSummary(result: AddToRecruitmentResult): string {
  const { job, response, restored } = result;
  if (restored) return `Przywrócono ${restored} ${peopleAccusative(restored)} do „${job.title}”.`;
  const head = addedSentence(job, response.total_added);
  if (response.total_skipped === 0) return head;
  const reasons = formatReasonCounts(summarizeBulkResult(response).skipped);
  return `${head} Pominięto: ${reasons || response.total_skipped}.`;
}

/** Kolumna, do której wraca karta — etap, na który trafiłoby to dodanie. */
function restoreLabel(closed: BulkClosedCard): string {
  if (closed.restore_stage === "new") return "Przywróć do „Nowych”";
  if (closed.restore_stage === "screening") return "Przywróć do „Screeningu”";
  return "Przywróć do rekrutacji";
}

/** Powód dla osób pominiętych bez zamkniętej karty: zdanie z serwera albo liczniki. */
function otherSkippedText(rows: BulkSkippedRow[]): string | null {
  if (rows.length === 0) return null;
  if (rows.length === 1 && rows[0].reason_label) return rows[0].reason_label;
  const counts = summarizeBulkResult({ added: [], skipped: rows, total_added: 0, total_skipped: rows.length });
  return `Pominięto: ${formatReasonCounts(counts.skipped)}.`;
}

interface AddToRecruitmentOutcomeProps {
  /** „Dodano N osób do …” albo „Nikogo nie dodano do …”. */
  headline: string;
  closedRows: ClosedRow[];
  /** Powód dla pominiętych bez zamkniętej karty. */
  otherText: string | null;
  restoredIds: ReadonlySet<number>;
  restoringId: number | null;
  onRestore: (row: ClosedRow) => void;
}

/** Wynik dodania, który wymaga uwagi: zamknięte karty i powody pominięcia. */
export function AddToRecruitmentOutcome({
  headline,
  closedRows,
  otherText,
  restoredIds,
  restoringId,
  onRestore,
}: AddToRecruitmentOutcomeProps) {
  return (
    <div role="alert" className="space-y-3 text-sm">
      <p className="text-foreground">{headline}</p>
      {closedRows.length > 0 ? (
        <>
          <ul className="space-y-2">
            {closedRows.map((row) => (
              <li
                key={row.candidate_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/40 bg-warning-muted p-3 text-warning-muted-foreground"
              >
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{row.closed.candidate_name}</span>
                  {" — "}
                  {row.reason_label ?? "Zamknięta karta w tej rekrutacji"}
                </span>
                {restoredIds.has(row.candidate_id) ? (
                  <span className="font-medium">Przywrócono</span>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onRestore(row)}
                    loading={restoringId === row.candidate_id}
                    disabled={restoringId != null}
                  >
                    {restoreLabel(row.closed)}
                  </Button>
                )}
              </li>
            ))}
          </ul>
          <p className="text-muted-foreground">
            Przywrócenie zaczyna nowe podejście w tej rekrutacji. Historia zamknięcia zostaje na karcie.
          </p>
        </>
      ) : null}
      {otherText ? <p className="text-destructive">{otherText}</p> : null}
    </div>
  );
}

export function AddToRecruitmentDialog({
  open,
  onOpenChange,
  candidateIds,
  source,
  runId,
  subject,
  onAdded,
}: AddToRecruitmentDialogProps) {
  const queryClient = useQueryClient();
  const [job, setJob] = useState<JobPickerJob | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ job: JobPickerJob; response: BulkProposalsResponse } | null>(null);
  const [restoredIds, setRestoredIds] = useState<ReadonlySet<number>>(new Set());
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const move = usePipelineMoveCore({ jobId: (result?.job ?? job)?.id ?? 0 });

  const reset = () => {
    setJob(null);
    setError(null);
    setResult(null);
    setRestoredIds(new Set());
  };

  const close = (next: boolean) => {
    if (pending || restoringId != null) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const submit = async () => {
    if (!job || candidateIds.length === 0) return;
    setPending(true);
    setError(null);
    try {
      const response = await proposalsBulkApi.add(job.id, {
        candidate_ids: candidateIds,
        source,
        ...(runId ? { run_id: runId } : {}),
      });
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(job.id)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", job.id] });
      void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      void queryClient.invalidateQueries({ queryKey: ["my-next-steps"] });
      // Zostajemy tylko, gdy jest co zrobić (zamknięta karta) albo nic się nie
      // dodało — „18 dodanych, 2 już były” zamyka okno jak dotąd.
      const stay =
        response.skipped.some(isClosedRow) ||
        (response.total_added === 0 && response.total_skipped > 0);
      if (stay) setResult({ job, response });
      else {
        setJob(null);
        onOpenChange(false);
      }
      if (response.total_added > 0 || !stay) onAdded?.({ job, response });
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się dodać do rekrutacji."));
    } finally {
      setPending(false);
    }
  };

  const closedRows = result ? result.response.skipped.filter(isClosedRow) : [];
  const otherRows = result ? result.response.skipped.filter((row) => !isClosedRow(row)) : [];

  const restore = async (row: ClosedRow) => {
    if (!result) return;
    const target = result.job;
    setRestoringId(row.candidate_id);
    let restored = false;
    try {
      const outcome = await move.send(
        {
          candidate_id: row.candidate_id,
          job_id: target.id,
          stage: row.closed.restore_stage,
          ...(row.closed.restore_stage_def_id != null ? { stage_def_id: row.closed.restore_stage_def_id } : {}),
          expected_state_version: row.closed.state_version,
        },
        {
          candidateName: row.closed.candidate_name,
          eligibilitySubject: row.closed.candidate_name,
          fallbackMessage: "Nie udało się przywrócić karty.",
        },
      );
      restored = outcome.ok;
    } finally {
      setRestoringId(null);
    }
    if (!restored) return;
    void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
    void queryClient.invalidateQueries({ queryKey: ["my-next-steps"] });
    const done = new Set(restoredIds).add(row.candidate_id);
    if (otherRows.length === 0 && closedRows.every((r) => done.has(r.candidate_id))) {
      reset();
      onOpenChange(false);
    } else {
      setRestoredIds(done);
    }
    onAdded?.({
      job: target,
      response: { added: [row.candidate_id], skipped: [], total_added: 1, total_skipped: 0 },
      restored: 1,
    });
  };

  const count = candidateIds.length;
  // Po zapisie ekran-rodzic czyści zaznaczenie, więc opis wyniku nie może
  // liczyć osób z propsa („dla 0 osób”).
  const description = result
    ? `Rekrutacja „${result.job.title}”.`
    : (subject ?? (count === 1 ? "Wybierz rekrutację dla tej osoby." : `Wybierz rekrutację dla ${count} osób.`));
  const otherText = otherSkippedText(otherRows);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Dodaj do rekrutacji</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[60dvh] overflow-y-auto">
          {result ? (
            <AddToRecruitmentOutcome
              headline={addedSentence(result.job, result.response.total_added)}
              closedRows={closedRows}
              otherText={otherText}
              restoredIds={restoredIds}
              restoringId={restoringId}
              onRestore={(row) => void restore(row)}
            />
          ) : (
            <>
              <JobPicker value={job} onChange={setJob} />
              {error ? (
                <p role="alert" className="mt-3 text-sm text-destructive">
                  {error}
                </p>
              ) : null}
            </>
          )}
        </DialogBody>
        <DialogFooter>
          {result ? (
            <Button variant="outline" onClick={() => close(false)} disabled={restoringId != null}>
              Zamknij
            </Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => close(false)} disabled={pending}>
                Anuluj
              </Button>
              <Button onClick={() => void submit()} disabled={!job || count === 0} loading={pending}>
                {job ? `Dodaj do „${job.title}”` : "Dodaj"}
              </Button>
            </>
          )}
        </DialogFooter>
        {/* Okna ruchu karty („Przenieś mimo to”) — jak w kolejce Cpro. */}
        {move.dialogs}
      </DialogContent>
    </Dialog>
  );
}
