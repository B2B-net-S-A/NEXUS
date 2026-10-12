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
 */

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  proposalsBulkApi,
  type BulkAddSource,
  type BulkProposalsResponse,
} from "@/lib/candidate-search-api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatReasonCounts, summarizeBulkResult } from "@/lib/bulk-result-summary";
import { pluralPl } from "@/lib/plural-pl";
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
import { JobPicker, type JobPickerJob } from "./JobPicker";

export interface AddToRecruitmentResult {
  job: JobPickerJob;
  response: BulkProposalsResponse;
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
  onAdded?: (result: AddToRecruitmentResult) => void;
}

/** „1 osobę”, „2 osoby”, „5 osób”, „22 osoby” — biernik liczebnika. */
function peopleAccusative(n: number): string {
  if (n === 1) return "osobę";
  const mod10 = n % 10;
  const mod100 = n % 100;
  return mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14) ? "osoby" : "osób";
}

export function addToRecruitmentSummary(result: AddToRecruitmentResult): string {
  const { job, response } = result;
  const added = response.total_added;
  const skipped = response.total_skipped;
  const head =
    added === 0
      ? `Nikogo nie dodano do „${job.title}”.`
      : `Dodano ${added} ${peopleAccusative(added)} do „${job.title}”.`;
  // Osoba z ostrzeżeniem JEST dodana (konflikt z klientem, praca u tego
  // klienta) — do 12.10.2026 okno gubiło tę część odpowiedzi.
  const warnings = summarizeBulkResult(response).warnings;
  return [
    head,
    skipped > 0 ? `Pominięto: ${skipped}.` : null,
    warnings.length > 0 ? `Uwaga: ${formatReasonCounts(warnings)}.` : null,
  ]
    .filter(Boolean)
    .join(" ");
}

function withoutLabel(n: number): string {
  return n === 1
    ? "Dodaj bez tej osoby"
    : `Dodaj bez tych ${n} ${pluralPl(n, "osoby", "osób", "osób")}`;
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
  const [skipEmployed, setSkipEmployed] = useState(false);

  const employedInSelection = useMemo(() => {
    const selected = new Set(candidateIds);
    return (employed ?? []).filter((person) => selected.has(person.id));
  }, [candidateIds, employed]);
  const idsToAdd = useMemo(() => {
    if (!skipEmployed) return candidateIds;
    const skipped = new Set(employedInSelection.map((person) => person.id));
    return candidateIds.filter((id) => !skipped.has(id));
  }, [candidateIds, employedInSelection, skipEmployed]);

  const close = (next: boolean) => {
    if (pending) return;
    if (!next) {
      setJob(null);
      setError(null);
      setSkipEmployed(false);
    }
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
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(job.id)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", job.id] });
      void queryClient.invalidateQueries({ queryKey: ["pipeline-scores"] });
      void queryClient.invalidateQueries({ queryKey: ["my-next-steps"] });
      onAdded?.({ job, response });
      setJob(null);
      setSkipEmployed(false);
      onOpenChange(false);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się dodać do rekrutacji."));
    } finally {
      setPending(false);
    }
  };

  const count = idsToAdd.length;
  const employedCount = employedInSelection.length;
  const description =
    subject ?? (count === 1 ? "Wybierz rekrutację dla tej osoby." : `Wybierz rekrutację dla ${count} osób.`);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Dodaj do rekrutacji</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[60dvh] overflow-y-auto">
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
          {error ? (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)} disabled={pending}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={!job || count === 0} loading={pending}>
            {job ? `Dodaj do „${job.title}”` : "Dodaj"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
