"use client";

import { useId, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  EXTENSION_LABELS,
  FEEDBACK_CHANNEL_LABELS,
  FEEDBACK_NOTE_MAX,
  SCORE_LABELS,
  scoresForPayload,
  useSaveClientFeedback,
  type ExtensionOutlook,
  type FeedbackChannel,
  type OrgConsultant,
  type ScoreField,
} from "@/lib/api/client-people";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

const FIELDS: ScoreField[] = ["quality", "communication", "autonomy"];
const EXTENSIONS: ExtensionOutlook[] = ["yes", "likely", "unsure", "no"];

export interface ClientFeedbackDialogProps {
  clientId: number;
  clientName: string;
  manager: { id: number; name: string };
  consultants: OrgConsultant[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function ScorePicker({
  label,
  groupLabel,
  value,
  disabled,
  onChange,
}: {
  label: string;
  /** Nazwa grupy dla czytnika ekranu — z osobą, bo grup jest kilka. */
  groupLabel: string;
  value: number | null;
  disabled: boolean;
  onChange: (value: number | null) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <div role="group" aria-label={groupLabel} className="inline-flex gap-1">
        {[1, 2, 3, 4, 5].map((score) => (
          <button
            key={score}
            type="button"
            disabled={disabled}
            aria-pressed={value === score}
            aria-label={`${groupLabel}: ${score}`}
            onClick={() => onChange(value === score ? null : score)}
            className={cn(
              "inline-flex size-7 items-center justify-center rounded-md border text-xs tabular-nums transition-colors disabled:opacity-50",
              value === score
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-card text-foreground hover:bg-muted",
            )}
          >
            {score}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * „Zapisz opinię” — rozmowa z menedżerem u klienta o jego konsultantach (D9–D11).
 *
 * Zapisuje ją opiekun albo Delivery Lead po rozmowie; formularza wysyłanego do
 * klienta nie ma (D10). Konsultant bez ani jednej oceny („pomiń”) nie dostaje
 * wiersza opinii.
 */
export function ClientFeedbackDialog({
  clientId,
  clientName,
  manager,
  consultants,
  open,
  onOpenChange,
}: ClientFeedbackDialogProps) {
  const { showToast } = useToast();
  const save = useSaveClientFeedback(clientId);
  const today = warsawToday();
  const ids = { date: useId(), channel: useId(), note: useId(), extension: useId() };
  const [heldOn, setHeldOn] = useState(today);
  const [channel, setChannel] = useState<FeedbackChannel>("phone");
  const [scores, setScores] = useState<
    Record<number, Partial<Record<ScoreField, number | null>>>
  >({});
  const [skipped, setSkipped] = useState<Set<number>>(new Set());
  const [extension, setExtension] = useState<ExtensionOutlook | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const nearestEnd = consultants
    .map((c) => c.end_date)
    .filter((value): value is string => Boolean(value))
    .sort()[0];

  const setScore = (contractId: number, field: ScoreField, value: number | null) =>
    setScores((current) => ({
      ...current,
      [contractId]: { ...current[contractId], [field]: value },
    }));
  const toggleSkip = (contractId: number) =>
    setSkipped((current) => {
      const next = new Set(current);
      if (next.has(contractId)) next.delete(contractId);
      else next.add(contractId);
      return next;
    });

  const submit = () => {
    setError(null);
    if (!heldOn || heldOn > today) {
      setError("Podaj datę rozmowy (najpóźniej dzisiejszą).");
      return;
    }
    save.mutate(
      {
        contact_id: manager.id,
        held_on: heldOn,
        channel,
        extension_outlook: extension,
        note: note.trim() || null,
        scores: scoresForPayload(scores, skipped),
      },
      {
        onSuccess: () => {
          showToast("Opinia zapisana", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać opinii.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Opinia od: ${manager.name} · ${clientName}`}
      description="Rozmowa z menedżerem u klienta o pracy naszych konsultantów."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz opinię"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Rozmowa" htmlFor={ids.channel}>
          <Select value={channel} onValueChange={(value) => setChannel(value as FeedbackChannel)}>
            <SelectTrigger id={ids.channel}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(FEEDBACK_CHANNEL_LABELS) as FeedbackChannel[]).map((key) => (
                <SelectItem key={key} value={key}>
                  {FEEDBACK_CHANNEL_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Data" htmlFor={ids.date} required>
          <Input
            id={ids.date}
            type="date"
            value={heldOn}
            max={today}
            onChange={(event) => setHeldOn(event.target.value)}
          />
        </FormField>
      </div>

      <div className="mt-3 space-y-2">
        {consultants.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Ta osoba nie jest menedżerem żadnego z naszych konsultantów — opinia zapisze
            samą rozmowę.
          </p>
        ) : null}
        {consultants.map((consultant) => {
          const isSkipped = skipped.has(consultant.contract_id);
          const values = scores[consultant.contract_id] ?? {};
          const name = consultant.candidate_name ?? `Kontrakt #${consultant.contract_id}`;
          return (
            <div
              key={consultant.contract_id}
              className="flex flex-wrap items-end justify-between gap-3 rounded-md border border-border/60 p-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium">{name}</p>
                <p className="text-xs text-muted-foreground">
                  {[
                    consultant.role,
                    consultant.end_date
                      ? `${consultant.end_source === "contract" ? "umowa" : "zamówienie"} do ${formatIsoDatePl(consultant.end_date)}`
                      : null,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "—"}
                </p>
                {isSkipped ? (
                  <p className="text-xs text-muted-foreground">bez opinii w tej rozmowie</p>
                ) : null}
              </div>
              <div className="flex flex-wrap items-end gap-3">
                {FIELDS.map((field) => (
                  <ScorePicker
                    key={field}
                    label={SCORE_LABELS[field]}
                    groupLabel={`${SCORE_LABELS[field]} — ${name}`}
                    value={values[field] ?? null}
                    disabled={isSkipped}
                    onChange={(value) => setScore(consultant.contract_id, field, value)}
                  />
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  aria-pressed={isSkipped}
                  aria-label={isSkipped ? `Oceń: ${name}` : `Pomiń: ${name}`}
                  onClick={() => toggleSkip(consultant.contract_id)}
                >
                  {isSkipped ? "oceń" : "pomiń"}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span id={ids.extension} className="text-sm">
          Przedłużenie{nearestEnd ? ` zamówień do ${formatIsoDatePl(nearestEnd)}` : ""}
        </span>
        <SegmentedRadio
          labelledBy={ids.extension}
          size="sm"
          value={extension}
          onChange={(value) => setExtension(value === extension ? null : value)}
          options={EXTENSIONS.map((value) => ({ value, label: EXTENSION_LABELS[value] }))}
        />
      </div>

      <FormField label="Co mówi klient" htmlFor={ids.note} className="mt-3">
        <Textarea
          id={ids.note}
          rows={3}
          maxLength={FEEDBACK_NOTE_MAX}
          value={note}
          placeholder="np. Zespół chce zostać w tym składzie. Więcej inicjatywy na planowaniu."
          onChange={(event) => setNote(event.target.value)}
        />
      </FormField>
      <p className="mt-2 text-xs text-muted-foreground">
        Konsultant tej opinii nie widzi. Bez danych o zdrowiu i bez stawek. Opinia trafia
        do kontraktów ocenionych osób.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
