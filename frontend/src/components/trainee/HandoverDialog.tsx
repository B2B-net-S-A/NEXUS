"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { apiErrorMessage } from "@/lib/api-error";
import { useTraineeHandover, useTraineeOpenJobs } from "@/lib/api/trainee";
import { WANTS_MAX } from "@/lib/trainee-call";

interface HandoverDialogProps {
  /** `null` = okno zamknięte. */
  itemId: number | null;
  personName: string;
  initialNote: string;
  onClose: () => void;
  onDone: (message: string) => void;
}

/**
 * „Przekaż rekruterowi” (makieta „Przekaz”): wybór otwartej rekrutacji, do
 * której osoba pasuje, i notatka. Osoba trafia do „Do przejrzenia” jako
 * propozycja — rekruter sam decyduje, czy dzwoni.
 */
export function HandoverDialog({
  itemId,
  personName,
  initialNote,
  onClose,
  onDone,
}: HandoverDialogProps) {
  const open = itemId != null;
  const jobs = useTraineeOpenJobs(itemId);
  const handover = useTraineeHandover();
  const [jobId, setJobId] = useState<string>("");
  const [note, setNote] = useState(initialNote);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setNote(initialNote);
    setError(null);
    setJobId("");
  }, [open, itemId, initialNote]);

  useEffect(() => {
    // Jedna rekrutacja do wyboru = zaznaczona od razu.
    if (jobs.data && jobs.data.length === 1 && jobId === "") {
      setJobId(String(jobs.data[0].job_id));
    }
  }, [jobs.data, jobId]);

  const submit = () => {
    if (itemId == null || jobId === "") return;
    setError(null);
    handover.mutate(
      { itemId, body: { job_id: Number(jobId), note: note.trim() } },
      {
        onSuccess: () => {
          const title = jobs.data?.find((j) => String(j.job_id) === jobId)?.title;
          onDone(
            `Przekazano rekruterowi: ${personName} — osoba jest w „Do przejrzenia”${title ? ` rekrutacji „${title}”` : ""}. Rekruter zdecyduje, czy dzwoni.`,
          );
        },
        onError: (err) =>
          setError(apiErrorMessage(err, "Nie udało się przekazać osoby. Spróbuj ponownie.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={`Przekaż rekruterowi — ${personName}`}
      description="Osoba trafi do „Do przejrzenia” wybranej rekrutacji jako propozycja. Rekruter decyduje, czy do niej dzwoni."
      size="lg"
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={handover.isPending}>
            Anuluj
          </Button>
          <Button
            onClick={submit}
            loading={handover.isPending}
            disabled={jobId === "" || handover.isPending}
          >
            Przekaż
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <span id="handover-jobs" className="text-sm font-medium text-foreground">
            Do której otwartej rekrutacji pasuje
          </span>
          {jobs.isError ? (
            <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-destructive">
              Nie udało się wczytać rekrutacji.
              <Button variant="outline" size="sm" onClick={() => jobs.refetch()}>
                Ponów
              </Button>
            </div>
          ) : jobs.isSuccess && jobs.data.length === 0 ? (
            <p className="rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
              Ta osoba nie pasuje dziś do żadnej otwartej rekrutacji. Rozmowa i tak zostaje w
              profilu — rekruterzy znajdą ją w wyszukiwarce.
            </p>
          ) : jobs.isSuccess ? (
            <RadioGroup
              aria-labelledby="handover-jobs"
              value={jobId}
              onValueChange={setJobId}
              className="gap-2"
            >
              {jobs.data.map((job) => {
                const id = `handover-job-${job.job_id}`;
                return (
                  <label
                    key={job.job_id}
                    htmlFor={id}
                    className="flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border border-border px-3 py-2.5 hover:bg-muted has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5"
                  >
                    <RadioGroupItem id={id} value={String(job.job_id)} className="mt-0.5" />
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="text-sm font-semibold text-foreground">
                        {job.title}{" "}
                        <span className="font-normal text-muted-foreground">#{job.job_id}</span>
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Prowadzi: {job.recruiter_name ?? "nieprzypisany"}
                        {job.matched_skills.length
                          ? ` · pokrywa must-have: ${job.matched_skills.join(", ")}`
                          : ""}
                      </span>
                    </span>
                  </label>
                );
              })}
            </RadioGroup>
          ) : (
            <p className="text-sm text-muted-foreground">Wczytuję rekrutacje…</p>
          )}
          <p className="text-xs text-muted-foreground">
            Widzisz tylko nazwę rekrutacji i osobę prowadzącą — bez klienta i budżetu.
          </p>
        </div>
        <div className="flex flex-col gap-2">
          <label htmlFor="handover-note" className="text-sm font-medium text-foreground">
            Co powinien wiedzieć rekruter
          </label>
          <textarea
            id="handover-note"
            rows={4}
            maxLength={WANTS_MAX}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-hidden"
          />
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
