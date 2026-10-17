"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  CADENCE_LEVELS,
  CADENCE_LEVEL_HINTS,
  CADENCE_REASON_LABELS,
  useContractCadence,
  useSetContractCadence,
  type CadenceHistoryStep,
  type CadenceLevel,
  type CadencePayload,
  type CadenceUpcoming,
} from "@/lib/api/care";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { formatDayMonthPl, formatIsoDatePl, monthYearPl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

import { cadenceLabel, cadenceTitle, signalText, talksText } from "./cadence-format";
import { shiftIso } from "./week/week-format";

const REASONS = (Object.keys(CADENCE_REASON_LABELS) as CadencePayload["reason"][]).filter(
  (reason) => (reason as string) !== "imported",
);
const NOTE_MAX = 500;

interface CadenceDialogProps {
  contractId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function historyText(step: CadenceHistoryStep): string {
  const level = cadenceTitle(step.level);
  if (step.kind === "start") {
    return step.level === "biweekly" ? `Start · ${cadenceLabel(step.level)} (pierwsze 90 dni)` : `Start · ${cadenceLabel(step.level)}`;
  }
  if (step.kind === "program_end") return `${level} · automatycznie po 90 dniach`;
  if (step.kind === "return") return `${level} · wraca po dacie „do kiedy”`;
  return [
    level,
    step.author?.name ?? null,
    step.note ? `„${step.note}”` : step.reason ? CADENCE_REASON_LABELS[step.reason].toLowerCase() : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function UpcomingList({ items }: { items: CadenceUpcoming[] }) {
  if (!items.length) return <span className="text-muted-foreground">brak w najbliższych miesiącach</span>;
  return (
    <span className="tabular-nums">
      {items.map((item, index) => (
        <span key={`${item.kind}-${item.due_on}`}>
          {index ? ", " : ""}
          <span className={index === 0 ? "font-semibold" : undefined}>{formatDayMonthPl(item.due_on)}</span>
          {item.kind === "pre_end" ? " (przed końcem)" : ""}
        </span>
      ))}
    </span>
  );
}

/**
 * „Rytm kontaktu” (makieta M2): poziom, powód z listy, notatka i opcjonalne
 * „do kiedy” (potem wraca poprzedni rytm). Obok podgląd zmiany liczony przez
 * serwer (najbliższe rozmowy, rozmowy opiekuna w następnym miesiącu)
 * i historia rytmu. Kamienie zostają przy każdym rytmie.
 */
export function CadenceDialog({ contractId, open, onOpenChange }: CadenceDialogProps) {
  const { showToast } = useToast();
  const today = warsawToday();
  const [level, setLevel] = useState<CadenceLevel | null>(null);
  const [reason, setReason] = useState<CadencePayload["reason"] | "">("");
  const [note, setNote] = useState("");
  const [until, setUntil] = useState("");
  const [noEnd, setNoEnd] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const untilValue = !noEnd && until > today ? until : null;
  const query = useContractCadence(contractId, { level, until: untilValue }, open);
  const save = useSetContractCadence(contractId);
  const data = query.data;
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  const now = data?.current.level ?? null;
  const preview = level && data?.preview?.level === level ? data.preview : null;

  const submit = () => {
    setError(null);
    if (!level) {
      setError("Wybierz, jak często rozmawiamy.");
      return;
    }
    if (!reason) {
      setError("Wybierz powód zmiany.");
      return;
    }
    if (!noEnd && !(until > today)) {
      setError("Data „do kiedy” musi być późniejsza niż dziś.");
      return;
    }
    save.mutate(
      { level, reason, note: note.trim() || null, until_on: noEnd ? null : until },
      {
        onSuccess: () => {
          showToast("Rytm zapisany", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać rytmu.")),
      },
    );
  };

  const subtitle = data
    ? [data.client_name, data.manager ? `menedżer: ${data.manager.name}` : null].filter(Boolean).join(" · ")
    : undefined;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Rytm kontaktu${data?.candidate_name ? ` · ${data.candidate_name}` : ""}`}
      description={subtitle}
      size="xl"
      footer={
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">Zmianę widzi DL klienta na osi konsultanta.</span>
          <span className="flex gap-2">
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Anuluj
            </Button>
            {data?.can_edit ? (
              <Button onClick={submit} disabled={save.isPending}>
                {save.isPending ? "Zapisywanie…" : "Zapisz rytm"}
              </Button>
            ) : null}
          </span>
        </div>
      }
    >
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie rytmu…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" || !data ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={apiErrorMessage(query.error, "Nie udało się wczytać rytmu.")}
          onRetry={() => query.refetch()}
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,300px)]">
          <div className="grid content-start gap-3">
            <div className="grid gap-1.5">
              <span id="cadence-level-label" className="text-sm font-medium text-foreground">
                Jak często rozmawiamy
              </span>
              <RadioGroup
                aria-labelledby="cadence-level-label"
                value={level ?? ""}
                onValueChange={(value) => setLevel(value as CadenceLevel)}
                disabled={!data.can_edit}
                className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5"
              >
                {CADENCE_LEVELS.map((option) => (
                  <label
                    key={option}
                    htmlFor={`cadence-${option}`}
                    className={cn(
                      "grid cursor-pointer gap-0.5 rounded-lg border border-border bg-card px-2.5 py-2 text-xs",
                      level === option && "border-primary bg-primary/10",
                    )}
                  >
                    <span className="flex items-center gap-1.5 text-sm font-medium text-foreground">
                      <RadioGroupItem
                        id={`cadence-${option}`}
                        value={option}
                        aria-label={cadenceTitle(option)}
                        aria-describedby={`cadence-${option}-hint`}
                      />
                      {cadenceTitle(option)}
                    </span>
                    <span id={`cadence-${option}-hint`} className="text-muted-foreground">
                      {now === option ? "teraz · " : ""}
                      {CADENCE_LEVEL_HINTS[option]}
                    </span>
                  </label>
                ))}
              </RadioGroup>
              {data.current.source !== "period" ? (
                <p className="text-xs text-muted-foreground">
                  Teraz: {cadenceLabel(data.current.level)}
                  {data.current.source === "program" ? " (pierwsze 90 dni, potem co miesiąc)" : " (domyślnie)"}
                </p>
              ) : null}
            </div>
            {data.can_edit ? (
              <>
                <FormField label="Powód" htmlFor="cadence-reason" required>
                  <Select value={reason} onValueChange={(value) => setReason(value as CadencePayload["reason"])}>
                    <SelectTrigger id="cadence-reason">
                      <SelectValue placeholder="Wybierz powód" />
                    </SelectTrigger>
                    <SelectContent>
                      {REASONS.map((key) => (
                        <SelectItem key={key} value={key}>
                          {CADENCE_REASON_LABELS[key]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </FormField>
                <FormField
                  label="Notatka (opcjonalnie)"
                  htmlFor="cadence-note"
                  description="Bez danych o zdrowiu i bez stawek."
                >
                  <Textarea
                    id="cadence-note"
                    rows={2}
                    maxLength={NOTE_MAX}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                  />
                </FormField>
                <div className="grid gap-2 sm:grid-cols-[minmax(0,200px)_minmax(0,1fr)] sm:items-end">
                  <FormField label="Do kiedy" htmlFor="cadence-until">
                    <Input
                      id="cadence-until"
                      type="date"
                      value={until}
                      min={today}
                      disabled={noEnd}
                      onChange={(event) => setUntil(event.target.value)}
                    />
                  </FormField>
                  <label htmlFor="cadence-no-end" className="flex items-center gap-2 pb-2 text-sm text-foreground">
                    <Checkbox
                      id="cadence-no-end"
                      checked={noEnd}
                      onCheckedChange={(value) => setNoEnd(value === true)}
                    />
                    Bez daty końca (zmienię ręcznie)
                  </label>
                </div>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">
                Rytm zmienia opiekun kontraktu, Delivery Lead klienta, head back office albo administrator.
              </p>
            )}
            {data.signals.length ? (
              <p className="text-xs text-muted-foreground">
                Sygnały: {data.signals.map(signalText).join(" · ")}
                {data.suggested_level ? ` — podpowiedź: ${cadenceLabel(data.suggested_level)}` : ""}
              </p>
            ) : null}
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </div>
          <aside className="grid content-start gap-3 rounded-lg border border-border bg-muted/30 p-3 text-sm">
            <section aria-label="Co się zmieni" className="grid gap-1.5">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {preview ? "Co się zmieni" : "Najbliższe rozmowy"}
              </h3>
              <dl className="grid gap-1">
                <dt className="text-xs text-muted-foreground">Najbliższe rozmowy</dt>
                <dd>
                  <UpcomingList items={preview ? preview.upcoming : data.upcoming} />
                </dd>
                {preview?.until_on && preview.returns_to ? (
                  <>
                    <dt className="text-xs text-muted-foreground">
                      Od {formatIsoDatePl(shiftIso(preview.until_on, 1))}
                    </dt>
                    <dd>{cadenceLabel(preview.returns_to)}</dd>
                  </>
                ) : null}
                <dt className="text-xs text-muted-foreground">Kamienie</dt>
                <dd>
                  7 dni po starcie i 30 dni przed końcem zamówienia
                  {data.end_date ? ` (${formatIsoDatePl(data.end_date)})` : ""} zostają zawsze
                </dd>
                {preview?.owner_month ? (
                  <>
                    <dt className="text-xs text-muted-foreground">
                      Rozmowy opiekuna ({preview.owner_month.owner.name}) ·{" "}
                      {monthYearPl(preview.owner_month.month.slice(0, 7))}
                    </dt>
                    <dd>
                      {talksText(preview.owner_month.after)} zamiast {preview.owner_month.before}
                    </dd>
                  </>
                ) : null}
              </dl>
            </section>
            <section aria-label="Historia rytmu" className="grid gap-1.5">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Historia rytmu
              </h3>
              <ol className="grid gap-1">
                {data.history.map((step, index) => (
                  <li
                    key={`${step.kind}-${step.on}-${index}`}
                    className={cn("grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2 text-xs", step.future && "text-muted-foreground")}
                  >
                    <span className="tabular-nums text-muted-foreground">{formatIsoDatePl(step.on)}</span>
                    <span className="min-w-0 break-words">{historyText(step)}</span>
                  </li>
                ))}
              </ol>
            </section>
          </aside>
        </div>
      )}
    </AppModal>
  );
}

