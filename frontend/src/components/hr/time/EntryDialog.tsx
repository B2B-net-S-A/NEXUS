"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import type {
  EntryPatch,
  MonthDay,
  TimesheetEntry,
  TimesheetTemplate,
} from "@/lib/api/hr-time";
import type { EmploymentType } from "@/lib/api/hr";
import { formatWeekdayDayPl } from "@/lib/date-pl";
import { capitalize, employmentTerms } from "@/lib/hr-employment-terms";

import { formatHours, parseHours, wouldExceedDay } from "./time-format";

export interface EntryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  day: MonthDay;
  /** `null` = nowy wpis. */
  entry: TimesheetEntry | null;
  /** Czy wolno wpisać nadgodziny (kartoteka albo Kadry) — serwer i tak sprawdza. */
  allowOvertime: boolean;
  /** Forma osoby: przy B2B i zleceniu „godziny ponad 8 h” zamiast „nadgodzin”. */
  form?: EmploymentType | null;
  onSave: (payload: EntryPatch & { id?: number }) => Promise<unknown>;
  onDelete?: (id: number) => Promise<unknown>;
  templates?: TimesheetTemplate[];
  /** Podpowiedź z pracy w NEXUSIE (tylko „Mój miesiąc”). */
  hint?: { text: string | null; loading: boolean } | null;
}

/** Wpis jednego dnia: godziny, projekt, opis; nadgodziny z uzasadnieniem. */
export function EntryDialog({
  open,
  onOpenChange,
  day,
  entry,
  allowOvertime,
  form,
  onSave,
  onDelete,
  templates = [],
  hint,
}: EntryDialogProps) {
  const words = employmentTerms(form);
  const { askConfirm, confirmDialog } = useConfirmV2();
  const defaultHours = entry ? entry.hours : Math.max(0, Math.min(8, day.capacity ?? 8) - day.hours);
  const [hours, setHours] = useState(formatHours(defaultHours || 8));
  const [project, setProject] = useState(entry?.project ?? "");
  const [description, setDescription] = useState(entry?.description ?? "");
  const [reason, setReason] = useState(entry?.overtime_reason ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const parsed = parseHours(hours);
  // Poprawka samego opisu albo projektu nie zmienia sumy dnia — nadgodziny
  // wpisu zostają, jak były (serwer robi to samo).
  const hoursUnchanged = entry != null && parsed === entry.hours;
  const overtime = hoursUnchanged
    ? entry.is_overtime
    : parsed != null && wouldExceedDay(day, parsed, entry?.hours ?? 0);

  const submit = async () => {
    setError(null);
    if (parsed == null || parsed <= 0) {
      setError("Podaj liczbę godzin większą od zera.");
      return;
    }
    if (!description.trim()) {
      setError("Opis jest wymagany.");
      return;
    }
    if (overtime && !allowOvertime && !hoursUnchanged) {
      setError(
        `Suma dnia przekroczyłaby 8 h. ${capitalize(words.overtime)} wpisuje osoba z uprawnieniem do ${words.overtime_genitive} albo Kadry.`,
      );
      return;
    }
    if (overtime && !hoursUnchanged && reason.trim().length < 5) {
      setError(`${words.overtime_reason_required} (co najmniej 5 znaków).`);
      return;
    }
    setBusy(true);
    try {
      await onSave({
        id: entry?.id,
        work_date: day.date,
        hours: parsed,
        project: project.trim() || null,
        description: description.trim(),
        overtime_reason: overtime ? reason.trim() || null : null,
      });
      onOpenChange(false);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się zapisać wpisu."));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!entry || !onDelete) return;
    const ok = await askConfirm({
      title: "Usunąć wpis?",
      description: `${formatWeekdayDayPl(day.date)} · ${formatHours(entry.hours)} h — wpis zniknie z timesheetu.`,
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    setBusy(true);
    try {
      await onDelete(entry.id);
      onOpenChange(false);
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się usunąć wpisu."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`${entry ? "Wpis" : "Nowy wpis"} · ${formatWeekdayDayPl(day.date)}`}
      description={
        day.capacity != null && day.capacity < 8
          ? `Pół dnia urlopu — do wpisania ${formatHours(day.capacity)} h.`
          : "Limit dnia to 8 h razem ze wszystkimi wpisami."
      }
      footer={
        <>
          {entry && onDelete ? (
            <Button variant="quiet" className="mr-auto" onClick={remove} disabled={busy}>
              Usuń wpis
            </Button>
          ) : null}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={busy}>
            {busy ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-[120px_minmax(0,1fr)]">
        <FormField label="Godziny" htmlFor="time-entry-hours">
          <Input
            id="time-entry-hours"
            inputMode="decimal"
            value={hours}
            onChange={(event) => setHours(event.target.value)}
          />
        </FormField>
        <FormField label="Projekt" htmlFor="time-entry-project" description="Opcjonalnie.">
          <Input
            id="time-entry-project"
            value={project}
            maxLength={200}
            onChange={(event) => setProject(event.target.value)}
          />
        </FormField>
        <FormField label="Opis" htmlFor="time-entry-description" className="sm:col-span-2">
          <Textarea
            id="time-entry-description"
            rows={3}
            value={description}
            maxLength={2000}
            onChange={(event) => setDescription(event.target.value)}
          />
        </FormField>
        {templates.length > 0 || hint ? (
          <div className="flex flex-wrap items-center gap-1.5 sm:col-span-2">
            {hint ? (
              <Button
                variant="outline"
                size="sm"
                disabled={hint.loading || !hint.text}
                title={hint.text ?? "Brak pracy w NEXUSIE tego dnia"}
                onClick={() => hint.text && setDescription(hint.text)}
              >
                {hint.loading ? "Szukam pracy z tego dnia…" : "Wstaw opis z pracy w NEXUSIE"}
              </Button>
            ) : null}
            {templates.map((template) => (
              <Button
                key={template.id}
                variant="ghost"
                size="sm"
                onClick={() => {
                  setDescription(template.description);
                  if (template.project && !project) setProject(template.project);
                }}
              >
                {template.name}
              </Button>
            ))}
          </div>
        ) : null}
        {hint?.text ? (
          <p className="text-xs text-muted-foreground sm:col-span-2">
            Podpowiedź: {hint.text}
          </p>
        ) : null}
        {overtime ? (
          <FormField
            label={words.overtime_reason}
            htmlFor="time-entry-reason"
            className="sm:col-span-2"
            description={
              allowOvertime
                ? words.overtime_reason_hint
                : `Nie masz uprawnienia do ${words.overtime_genitive} — popraw godziny albo poproś Kadry.`
            }
          >
            <Input
              id="time-entry-reason"
              value={reason}
              maxLength={1000}
              disabled={!allowOvertime}
              onChange={(event) => setReason(event.target.value)}
            />
          </FormField>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {confirmDialog}
    </AppModal>
  );
}
