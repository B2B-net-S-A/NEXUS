"use client";

/**
 * „Dodaj do rekrutacji” dla jednej albo wielu osób — z listy kandydatów
 * (`source="candidate_list"`) i z wyników Talent Radaru (`source="talent_radar"`).
 *
 * Zapis idzie przez to samo API co AI Matching (`POST /api/jobs/{id}/proposals/bulk`),
 * więc pomijanie osób już obecnych w rekrutacji, bramki klienta i telemetria
 * działają tak samo. Endpoint wymaga członkostwa w zespole rekrutacji — stąd
 * `JobPicker scope="mine"` i czytelny komunikat przy 403.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  proposalsBulkApi,
  type BulkAddSource,
  type BulkProposalsResponse,
} from "@/lib/candidate-search-api";
import { apiErrorMessage } from "@/lib/api-error";
import { isForbiddenError } from "@/lib/view-state";
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
  return skipped > 0 ? `${head} Pominięto: ${skipped}.` : head;
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

  const close = (next: boolean) => {
    if (pending) return;
    if (!next) {
      setJob(null);
      setError(null);
    }
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
      onAdded?.({ job, response });
      setJob(null);
      onOpenChange(false);
    } catch (err) {
      setError(
        isForbiddenError(err)
          ? "Nie należysz do zespołu tej rekrutacji."
          : apiErrorMessage(err, "Nie udało się dodać do rekrutacji."),
      );
    } finally {
      setPending(false);
    }
  };

  const count = candidateIds.length;
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
          <JobPicker value={job} onChange={setJob} scope="mine" />
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
