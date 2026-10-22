"use client";

/**
 * Blok „Pasuje też do” pod osobą dodaną w oknie „Kandydaci do dodania”
 * (14.10.2026, makieta A1). Prezentacja bez zapytań — dane i akcje daje
 * `useAlsoFitsJobs`. Procent to ta sama liczba, którą tamta rekrutacja pokazuje
 * w „Szukaj w bazie” (serwer: `services/also_fits.py`).
 */

import type { ReactNode } from "react";
import { ArrowLeftRight, Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ClientReferenceTag } from "@/components/v2/jobs/JobPickName";
import { formatDayMonthPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import type { AlsoFits, AlsoFitsRowModel } from "./useAlsoFitsJobs";

/** Zawartość `PickRow.alsoFits` dla osoby — `undefined`, gdy nie dodano jej w tym oknie. */
export function alsoFitsSlot(
  alsoFits: AlsoFits,
  candidateId: number,
  candidateName: string,
  readOnly: boolean,
): ReactNode {
  const model = alsoFits.forCandidate(candidateId);
  if (!model) return undefined;
  return (
    <AlsoFitsBlock
      model={model}
      candidateName={candidateName}
      readOnly={readOnly}
      onAdd={(jobIds) => alsoFits.add(candidateId, jobIds)}
      onUndo={(jobId) => alsoFits.undo(candidateId, jobId)}
      onRetry={() => alsoFits.recheck(candidateId)}
      onRequest={() => alsoFits.request(candidateId)}
    />
  );
}

export interface AlsoFitsBlockProps {
  model: AlsoFitsRowModel;
  candidateName: string;
  readOnly: boolean;
  onAdd: (jobIds: number[]) => void;
  onUndo: (jobId: number) => void;
  onRetry: () => void;
  onRequest: () => void;
}

/** „nasz konsultant · Wraca na rynek 31.10” — źródło osoby w bloku (R2, 22.10.2026). */
export function ourConsultantLabel(model: Pick<AlsoFitsRowModel, "ourConsultant">): string | null {
  if (!model.ourConsultant) return null;
  const { returnsOn } = model.ourConsultant;
  return returnsOn
    ? `nasz konsultant · Wraca na rynek ${formatDayMonthPl(returnsOn)}`
    : "nasz konsultant · Wraca na rynek";
}

function heading(count: number): string {
  return count === 1
    ? "Pasuje też do 1 innej rekrutacji"
    : `Pasuje też do ${count} innych rekrutacji`;
}

export function AlsoFitsBlock({
  model,
  candidateName,
  readOnly,
  onAdd,
  onUndo,
  onRetry,
  onRequest,
}: AlsoFitsBlockProps) {
  if (model.status === "idle") {
    return (
      <p className="mt-1 text-xs text-muted-foreground" data-testid="also-fits-idle">
        <button type="button" onClick={onRequest} className="font-semibold text-primary hover:underline">
          Sprawdź, gdzie jeszcze pasuje
        </button>
      </p>
    );
  }
  if (model.status === "loading") {
    return (
      <p role="status" className="mt-1 text-xs text-muted-foreground" data-testid="also-fits-loading">
        Sprawdzam inne rekrutacje…
      </p>
    );
  }
  if (model.status === "error" || model.status === "unavailable") {
    // Awaria nie może wyglądać jak „nic nie pasuje”.
    return (
      <p className="mt-1 text-xs text-warning-muted-foreground" data-testid="also-fits-error">
        Nie udało się sprawdzić innych rekrutacji ·{" "}
        <button type="button" onClick={onRetry} className="font-semibold text-primary hover:underline">
          Ponów
        </button>
      </p>
    );
  }
  if (model.jobs.length === 0) return null;

  const notAdded = model.jobs.filter((job) => !model.stateOf(job.job_id));
  return (
    <section
      aria-label={`Inne rekrutacje dla: ${candidateName}`}
      className="mt-2 rounded-lg border border-primary/30 bg-background px-3 py-2"
      data-testid="also-fits-block"
    >
      <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
        <ArrowLeftRight className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
        {heading(model.jobs.length)}
        {ourConsultantLabel(model) ? (
          <span className="font-normal text-muted-foreground" data-testid="also-fits-source">
            {" · "}
            {ourConsultantLabel(model)}
          </span>
        ) : null}
      </p>
      <ul className="mt-1 divide-y divide-border">
        {model.jobs.map((job) => {
          const state = model.stateOf(job.job_id);
          const error = model.errorOf(job.job_id);
          return (
            <li key={job.job_id} className="py-1.5" data-job-id={job.job_id}>
              <div className="flex items-center gap-2">
                {/* Numer zabiera miejsce tytułowi — pełna nazwa w dymku. */}
                <p
                  className="min-w-0 flex-1 truncate text-xs"
                  title={[job.client_reference, job.title, job.client_name].filter(Boolean).join(" · ")}
                >
                  <ClientReferenceTag reference={job.client_reference} className="mr-1 align-middle" />
                  <span className="font-semibold text-foreground">{job.title}</span>
                  {job.client_name ? (
                    <span className="text-muted-foreground"> · {job.client_name}</span>
                  ) : null}
                </p>
                <span className="shrink-0 text-xs font-bold tabular-nums text-primary">{job.score}%</span>
                {state === "added" || state === "undoing" ? (
                  <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-success-muted-foreground">
                    <Check className="h-3.5 w-3.5" aria-hidden="true" />
                    Dodano
                    {!readOnly && model.undoable(job.job_id) ? (
                      <>
                        <span aria-hidden="true">·</span>
                        <button
                          type="button"
                          onClick={() => onUndo(job.job_id)}
                          disabled={state === "undoing"}
                          aria-label={`Cofnij dodanie do: ${job.title}`}
                          className="font-semibold text-primary hover:underline disabled:opacity-60"
                        >
                          {state === "undoing" ? "Cofam…" : "Cofnij"}
                        </button>
                      </>
                    ) : null}
                  </span>
                ) : (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 shrink-0 px-2 text-xs"
                    disabled={readOnly || state === "adding"}
                    onClick={() => onAdd([job.job_id])}
                    aria-label={`Dodaj ${candidateName} też do: ${job.title}`}
                  >
                    {state === "adding" ? "Dodaję…" : "+ Dodaj"}
                  </Button>
                )}
              </div>
              {job.matching_must.length > 0 || job.gap_must.length > 0 ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {job.matching_must.map((label) => (
                    <span
                      key={`ok-${label}`}
                      className="rounded bg-success-muted px-1.5 text-[11px] font-semibold text-success-muted-foreground"
                    >
                      ✓ {label}
                    </span>
                  ))}
                  {job.gap_must.map((label) => (
                    <span
                      key={`gap-${label}`}
                      className="rounded bg-destructive-muted px-1.5 text-[11px] font-semibold text-destructive-muted-foreground"
                    >
                      ✕ {label}
                    </span>
                  ))}
                </div>
              ) : null}
              {error ? (
                <p role="alert" className="mt-1 text-xs text-destructive-muted-foreground">
                  {error}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      <div className={cn("mt-1 flex items-center gap-2 text-[11px]", notAdded.length > 1 ? "justify-between" : "justify-end")}>
        {notAdded.length > 1 && !readOnly ? (
          <button
            type="button"
            onClick={() => onAdd(notAdded.map((job) => job.job_id))}
            className="shrink-0 whitespace-nowrap font-semibold text-primary hover:underline"
          >
            Dodaj do wszystkich ({notAdded.length})
          </button>
        ) : null}
        <span className="text-right text-muted-foreground">% jak w „Szukaj w bazie” tamtej rekrutacji</span>
      </div>
    </section>
  );
}
