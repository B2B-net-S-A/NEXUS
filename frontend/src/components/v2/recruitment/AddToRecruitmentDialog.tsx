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
 *
 * Delivery Lead (uprawnienie wysyłki CV) przy jednej osobie wybiera etap:
 * „Nowi” albo od razu „Zweryfikowany” (decyzja Artura 22.10.2026 — DL sam
 * przeprowadza osobę, którą rekruter pominął). Dodanie idzie jak zawsze,
 * a drugi krok to zwykły ruch karty — serwer przepuszcza DL-a bez bramek pól
 * i zapisuje ślad braków (`requirements_skipped`).
 */

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  proposalsBulkApi,
  type BulkAddSource,
  type BulkClosedCard,
  type BulkProposalsResponse,
  type BulkSkippedRow,
} from "@/lib/candidate-search-api";
import { apiErrorMessage } from "@/lib/api-error";
import { useAuthStore } from "@/store/auth";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { pluralPl } from "@/lib/plural-pl";
import { usePipelineMoveCore } from "@/hooks/usePipelineMoveCore";
import type { PipelineMovePayload } from "@/lib/pipeline-move-core";
import {
  ADD_ANYWAY_HINT,
  EmployedPeopleNotice,
  type EmployedPerson,
} from "@/components/v2/employment/EmploymentNotice";
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
import { jobDisplayTitle } from "@/lib/job-names";
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
  /**
   * Osoby z wyboru, które u nas pracują — podaje ekran, który otwiera okno
   * (ma znacznik w wierszach). Okno informuje i pozwala dodać resztę bez nich.
   */
  employed?: EmployedPerson[];
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

// Rekrutacja nazwana jak w jej nagłówku — tytułem dla rekrutera (16.10.2026).
function addedSentence(job: JobPickerJob, added: number): string {
  return added === 0
    ? `Nikogo nie dodano do „${jobDisplayTitle(job)}”.`
    : `Dodano ${added} ${peopleAccusative(added)} do „${jobDisplayTitle(job)}”.`;
}

export function addToRecruitmentSummary(result: AddToRecruitmentResult): string {
  const { job, response, restored } = result;
  if (restored) return `Przywrócono ${restored} ${peopleAccusative(restored)} do „${jobDisplayTitle(job)}”.`;
  const summary = summarizeBulkResult(response);
  // Osoba z ostrzeżeniem JEST dodana (konflikt z klientem, praca u tego
  // klienta) — do 12.10.2026 okno gubiło tę część odpowiedzi.
  return [
    addedSentence(job, response.total_added),
    response.total_skipped > 0
      ? `Pominięto: ${formatReasonCounts(summary.skipped) || response.total_skipped}.`
      : null,
    summary.warnings.length > 0 ? `Uwaga: ${formatReasonCounts(summary.warnings)}.` : null,
  ]
    .filter(Boolean)
    .join(" ");
}

function withoutLabel(n: number): string {
  return n === 1
    ? "Dodaj bez tej osoby"
    : `Dodaj bez tych ${n} ${pluralPl(n, "osoby", "osób", "osób")}`;
}

/** Ruch, który przywraca zamkniętą kartę — cel i wersja z odpowiedzi serwera. */
export function restoreMovePayload(
  candidateId: number,
  jobId: number,
  closed: BulkClosedCard,
): PipelineMovePayload {
  return {
    candidate_id: candidateId,
    job_id: jobId,
    stage: closed.restore_stage,
    ...(closed.restore_stage_def_id != null ? { stage_def_id: closed.restore_stage_def_id } : {}),
    expected_state_version: closed.state_version,
  };
}

/** Kolumna, do której wraca karta — etap, na który trafiłoby to dodanie. */
export function restoreLabel(closed: BulkClosedCard): string {
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
  employed,
  onAdded,
}: AddToRecruitmentDialogProps) {
  const queryClient = useQueryClient();
  const [job, setJob] = useState<JobPickerJob | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ job: JobPickerJob; response: BulkProposalsResponse } | null>(null);
  const [restoredIds, setRestoredIds] = useState<ReadonlySet<number>>(new Set());
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [skipEmployed, setSkipEmployed] = useState(false);
  const [toVerified, setToVerified] = useState(false);
  const move = usePipelineMoveCore({ jobId: (result?.job ?? job)?.id ?? 0 });
  // Etap „Zweryfikowany” tylko dla konta, które serwer przepuszcza bez bramek
  // pól (`/api/auth/me` → `skips_fill_gates`, zna wyłącznik; F109).
  const canPickStage =
    useAuthStore((s) => s.user?.skips_fill_gates === true) && candidateIds.length === 1;

  const employedInSelection = useMemo(() => {
    const selected = new Set(candidateIds);
    return (employed ?? []).filter((person) => selected.has(person.id));
  }, [candidateIds, employed]);
  const idsToAdd = useMemo(() => {
    if (!skipEmployed) return candidateIds;
    const skipped = new Set(employedInSelection.map((person) => person.id));
    return candidateIds.filter((id) => !skipped.has(id));
  }, [candidateIds, employedInSelection, skipEmployed]);

  const reset = () => {
    setJob(null);
    setError(null);
    setResult(null);
    setRestoredIds(new Set());
    setSkipEmployed(false);
    setToVerified(false);
  };

  const close = (next: boolean) => {
    if (pending || restoringId != null) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const submit = async () => {
    if (!job || idsToAdd.length === 0) return;
    setPending(true);
    setError(null);
    try {
      const response = await proposalsBulkApi.add(job.id, {
        candidate_ids: idsToAdd,
        source,
        ...(runId ? { run_id: runId } : {}),
      });
      // DL: od razu na „Zweryfikowany” — zwykły ruch karty dodanej osoby.
      if (canPickStage && toVerified) {
        for (const candidateId of response.added) {
          await move.send(
            { candidate_id: candidateId, job_id: job.id, stage: "verified" },
            { candidateName: subject ?? "Kandydat", fallbackMessage: "Dodano do „Nowych”, ale nie udało się przesunąć na „Zweryfikowany”." },
          );
        }
      }
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
        setSkipEmployed(false);
        setToVerified(false);
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
        restoreMovePayload(row.candidate_id, target.id, row.closed),
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

  const count = idsToAdd.length;
  const employedCount = employedInSelection.length;
  // Po zapisie ekran-rodzic czyści zaznaczenie, więc opis wyniku nie może
  // liczyć osób z propsa („dla 0 osób”).
  const description = result
    ? `Rekrutacja „${jobDisplayTitle(result.job)}”.`
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
              {skipEmployed ? (
                <p
                  role="note"
                  className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
                >
                  <span>
                    Bez {employedCount} {pluralPl(employedCount, "osoby, która u nas pracuje", "osób, które u nas pracują", "osób, które u nas pracują")}.
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => setSkipEmployed(false)}>
                    Przywróć
                  </Button>
                </p>
              ) : (
                <EmployedPeopleNotice
                  people={employedInSelection}
                  total={candidateIds.length}
                  hint={ADD_ANYWAY_HINT}
                  className="mb-3"
                  action={
                    // Przycisk ma sens tylko, gdy po odjęciu ktoś zostaje.
                    employedCount > 0 && employedCount < candidateIds.length ? (
                      <Button size="sm" variant="outline" onClick={() => setSkipEmployed(true)}>
                        {withoutLabel(employedCount)}
                      </Button>
                    ) : undefined
                  }
                />
              )}
              <JobPicker value={job} onChange={setJob} />
              {canPickStage ? (
                <fieldset className="mt-3" data-testid="add-to-recruitment-stage">
                  <legend className="mb-1.5 text-xs font-semibold text-muted-foreground">Na etap</legend>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { value: false, label: "Nowi" },
                      { value: true, label: "Zweryfikowany" },
                    ].map((option) => (
                      <Button
                        key={option.label}
                        type="button"
                        variant={toVerified === option.value ? "primary" : "outline"}
                        aria-pressed={toVerified === option.value}
                        onClick={() => setToVerified(option.value)}
                      >
                        {option.label}
                      </Button>
                    ))}
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    {toVerified
                      ? "Przesuwasz jako Delivery Lead — bez arkusza i stawki; braki zostaną na karcie, a proces zaliczy się Tobie."
                      : "Osoba trafi do „Nowych”, jak przy dodaniu przez rekrutera."}
                  </p>
                </fieldset>
              ) : null}
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
                {job
                  ? canPickStage && toVerified
                    ? "Dodaj na „Zweryfikowany”"
                    : `Dodaj do „${jobDisplayTitle(job)}”`
                  : "Dodaj"}
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
