"use client";

/**
 * Czwarty fakt nagłówka rekrutacji: „Proces u klienta” (18.11.2026).
 * Etapy po wysłaniu CV, deklarowany termin decyzji, czas zmierzony na
 * ruchach kart u klienta i zdanie dla kandydata. Edycja po fakcie w tym
 * samym okienku („Zmień” / „Wpisz etapy”), przy tworzeniu — `/jobs/new`.
 * Reguła: `docs/claude/rekrutacja-tworzenie/proces-u-klienta.md`.
 */

import { useState } from "react";
import { Copy, Route } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ClientProcessEditor } from "@/components/v2/jobs/ClientProcessEditor";
import { apiErrorMessage } from "@/lib/api-error";
import {
  EMPTY_PROCESS,
  FORMAT_LABEL,
  stepName,
  candidateSentence,
  daysLabel,
  decisionSlowerThanDeclared,
  processFactLabel,
  toInput,
  type ClientProcess,
  type ClientProcessHints,
  type ClientProcessInput,
  type MeasuredProcess,
} from "@/lib/job-client-process";
import { useClientProcessHints, useSaveClientProcess } from "@/lib/job-client-process-api";
import { cn, formatDate } from "@/lib/utils";

interface JobClientProcessFactProps {
  jobId: number;
  clientId: number | null;
  clientName: string | null;
  process: ClientProcess | null;
  canEdit: boolean;
}

export function JobClientProcessFact({
  jobId,
  clientId,
  clientName,
  process,
  canEdit,
}: JobClientProcessFactProps) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<ClientProcessInput | null>(null);
  const hints = useClientProcessHints(clientId, jobId);
  const measured = hints.data?.measured ?? null;
  const label = processFactLabel(process, measured);

  const startEdit = (from: ClientProcessInput | null) =>
    setDraft(
      from
        ? { steps: from.steps.map((s) => ({ ...s })), decision_workdays: from.decision_workdays }
        : EMPTY_PROCESS,
    );

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setDraft(null);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2.5 focus-visible:outline-2 focus-visible:outline-primary",
            label
              ? "border-primary/20 bg-primary/5 hover:bg-primary/10"
              : "border-dashed border-border hover:bg-muted",
          )}
          data-testid="job-header-fact-process"
          data-tour="job.client-process"
          title={`Proces u klienta: ${label ?? "nie podano"}`}
        >
          <Route className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
          <span className="sr-only">Proces u klienta: </span>
          {/* Pusty proces poniżej szerokości nagłówka 86rem to sama ikona (19.11.2026): przy
              1280 px linia faktów nie mieściła „Dodana → Termin”, a „nie
              podano” zostaje w dymku i dla czytnika ekranu. */}
          <span
            className={cn(
              "whitespace-nowrap text-[13px] leading-tight",
              label ? "font-semibold text-foreground" : "hidden text-muted-foreground @min-[86rem]/job-header:inline",
            )}
          >
            {label ?? "proces: nie podano"}
          </span>
          {label ? null : <span className="sr-only @min-[86rem]/job-header:hidden">nie podano</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[480px] p-0" data-testid="client-process-popover">
        {draft ? (
          <EditMode
            jobId={jobId}
            draft={draft}
            onChange={setDraft}
            onDone={() => setDraft(null)}
          />
        ) : (
          <ViewMode
            process={process}
            hints={hints.data ?? null}
            hintsFailed={hints.isError}
            clientName={clientName}
            canEdit={canEdit}
            onEdit={startEdit}
          />
        )}
      </PopoverContent>
    </Popover>
  );
}

interface ViewModeProps {
  process: ClientProcess | null;
  hints: ClientProcessHints | null;
  hintsFailed: boolean;
  clientName: string | null;
  canEdit: boolean;
  onEdit: (from: ClientProcessInput | null) => void;
}

function ViewMode({ process, hints, hintsFailed, clientName, canEdit, onEdit }: ViewModeProps) {
  const measured = hints?.measured ?? null;
  const suggested = hints?.suggested ?? null;
  const sentence = candidateSentence(process, measured);
  const client = clientName?.trim() || "klienta";
  return (
    <div className="flex flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">Proces u klienta</p>
          {process?.set_by_name || process?.set_at ? (
            <p className="text-xs text-muted-foreground">
              Wpisał(a) {process.set_by_name ?? "—"}
              {process.set_at ? `, ${formatDate(process.set_at)}` : ""}
            </p>
          ) : null}
        </div>
        {canEdit && process ? (
          <Button size="sm" variant="outline" onClick={() => onEdit(process)}>
            Zmień
          </Button>
        ) : null}
      </div>

      {process ? (
        <ol className="flex flex-col gap-2 px-4 py-3" data-testid="client-process-steps">
          {process.steps.map((step, index) => (
            <li key={index} className="flex items-start gap-2.5">
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary">
                {index + 1}
              </span>
              <div className="min-w-0">
                <p className="text-sm font-medium">{stepName(step)}</p>
                <p className="text-xs text-muted-foreground">
                  {FORMAT_LABEL[step.format]}
                  {step.duration ? ` · ${step.duration}` : ""}
                </p>
              </div>
            </li>
          ))}
          {process.decision_workdays ? (
            <li className="text-sm">
              Decyzja klienta{" "}
              <span className="text-muted-foreground">
                — obiecuje do {process.decision_workdays} dni roboczych
              </span>
            </li>
          ) : null}
        </ol>
      ) : (
        <div className="flex flex-col gap-2 px-4 py-3">
          <p className="text-sm text-muted-foreground">
            Nikt jeszcze nie wpisał etapów u klienta po wysłaniu CV.
          </p>
          {canEdit && suggested ? (
            <div className="flex items-center justify-between gap-2 rounded-md bg-muted/60 px-3 py-2">
              <p className="min-w-0 text-xs">
                Poprzednia rekrutacja {client}:{" "}
                <b>{suggested.steps.map((s) => stepName(s)).join(" + ")}</b>
              </p>
              <Button size="sm" variant="outline" onClick={() => onEdit(suggested)}>
                Użyj
              </Button>
            </div>
          ) : null}
          {canEdit ? (
            <Button size="sm" className="self-start" onClick={() => onEdit(null)}>
              Wpisz etapy
            </Button>
          ) : null}
        </div>
      )}

      {measured ? (
        <MeasuredBlock measured={measured} client={client} process={process} />
      ) : hintsFailed ? (
        <p className="border-t border-border px-4 py-3 text-xs text-muted-foreground">
          Nie udało się wczytać czasu z historii — odśwież stronę.
        </p>
      ) : null}

      {sentence ? <CandidateSentence sentence={sentence} /> : null}
    </div>
  );
}

function MeasuredBlock({
  measured,
  client,
  process,
}: {
  measured: MeasuredProcess;
  client: string;
  process: ClientProcess | null;
}) {
  const first = measured.cv_to_interview_days;
  const second = measured.interview_to_decision_days;
  const split = first != null && second != null && first + second > 0 ? (first / (first + second)) * 100 : null;
  return (
    <div className="border-t border-border bg-muted/40 px-4 py-3" data-testid="client-process-measured">
      <p className="text-xs font-medium text-muted-foreground">
        Jak jest naprawdę u {client} · mediana z {measured.decisions} decyzji, {measured.months} mies.
      </p>
      {split != null ? (
        <div className="mt-2 flex h-2 overflow-hidden rounded-full" aria-hidden="true">
          <div className="bg-primary/40" style={{ width: `${split}%` }} />
          <div className="bg-primary" style={{ width: `${100 - split}%` }} />
        </div>
      ) : null}
      <div className="mt-1.5 flex flex-wrap justify-between gap-x-3 text-xs">
        {first != null ? (
          <span>
            CV → rozmowa <b>{daysLabel(first)}</b>
          </span>
        ) : null}
        {second != null ? (
          <span>
            rozmowa → decyzja <b>{daysLabel(second)}</b>
          </span>
        ) : null}
        <span className="font-semibold">razem ~{daysLabel(measured.cv_to_decision_days)}</span>
      </div>
      {decisionSlowerThanDeclared(process, measured) ? (
        <p className="mt-2 text-xs text-warning">
          Decyzja trwa dłużej, niż klient obiecuje — uprzedź kandydata.
        </p>
      ) : null}
    </div>
  );
}

function CandidateSentence({ sentence }: { sentence: string }) {
  const { showSuccess } = useToast();
  const [selectable, setSelectable] = useState(false);
  return (
    <div className="border-t border-border px-4 py-3">
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground">Powiedz kandydatowi</p>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 gap-1 px-2 text-xs"
          onClick={() => {
            navigator.clipboard
              ?.writeText(sentence)
              .then(() => showSuccess("Skopiowano zdanie dla kandydata"))
              .catch(() => setSelectable(true));
          }}
        >
          <Copy className="h-3 w-3" aria-hidden="true" />
          Kopiuj
        </Button>
      </div>
      <p className={cn("text-[13px] leading-snug", selectable && "select-all")} data-testid="client-process-sentence">
        {sentence}
      </p>
    </div>
  );
}

function EditMode({
  jobId,
  draft,
  onChange,
  onDone,
}: {
  jobId: number;
  draft: ClientProcessInput;
  onChange: (next: ClientProcessInput) => void;
  onDone: () => void;
}) {
  const save = useSaveClientProcess(jobId);
  const { showSuccess, showError } = useToast();
  const submit = () =>
    save.mutate(toInput(draft), {
      onSuccess: (data) => {
        showSuccess(data.client_process ? "Zapisano proces u klienta" : "Usunięto proces u klienta");
        onDone();
      },
      onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać procesu u klienta.")),
    });
  return (
    <div className="flex flex-col">
      <div className="border-b border-border px-4 py-3">
        <p className="text-sm font-semibold">Proces u klienta — etapy po wysłaniu CV</p>
      </div>
      <div className="px-4 py-3">
        <ClientProcessEditor value={draft} onChange={onChange} idPrefix={`job-${jobId}-process`} />
      </div>
      <div className="flex justify-end gap-2 border-t border-border px-4 py-2.5">
        <Button size="sm" variant="ghost" onClick={onDone} disabled={save.isPending}>
          Anuluj
        </Button>
        <Button size="sm" onClick={submit} loading={save.isPending}>
          Zapisz
        </Button>
      </div>
    </div>
  );
}
