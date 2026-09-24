"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useTraineeQualitySample,
  useTraineeQualityVerdict,
  type QualityVerdict,
  type TraineeQualitySampleItem,
} from "@/lib/api/trainee";
import { handoverNoteFromFacts, telHref } from "@/lib/trainee-call";
import { cn } from "@/lib/utils";

function SampleRow({
  row,
  userId,
}: {
  row: TraineeQualitySampleItem;
  userId: number;
}) {
  const verdict = useTraineeQualityVerdict(userId);
  const [note, setNote] = useState(row.note ?? "");
  const [error, setError] = useState<string | null>(null);
  const tel = telHref(row.phone);
  const facts = handoverNoteFromFacts({
    min_rate_hourly: null,
    rate_updated_at: null,
    b2b_willingness: null,
    accepts_below_min_rate: null,
    remote_modes: [],
    max_onsite_days: null,
    accepts_more_office_days: null,
    office_cities: [],
    work_time_preference: null,
    availability_status: null,
    availability_date: null,
    ...row.facts,
  });
  const save = (value: QualityVerdict) => {
    setError(null);
    verdict.mutate(
      { itemId: row.item_id, body: { verdict: value, note: note.trim() } },
      { onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać oceny.")) },
    );
  };
  const called = row.called_at
    ? new Date(row.called_at).toLocaleString("pl-PL", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">{row.name}</span>
        <span className="text-xs text-muted-foreground">
          {called ? `rozmowa ${called}` : "rozmowa bez daty"}
          {row.phone ? " · " : ""}
          {tel ? (
            <a href={tel} className="font-mono text-foreground underline-offset-4 hover:underline">
              {row.phone}
            </a>
          ) : null}
        </span>
      </div>
      <p className="text-sm text-muted-foreground">
        {facts || "Praktykant nie zapisał faktów z tej rozmowy."}
      </p>
      <label className="sr-only" htmlFor={`qs-note-${row.item_id}`}>
        Notatka do oceny — {row.name}
      </label>
      <textarea
        id={`qs-note-${row.item_id}`}
        rows={2}
        maxLength={1000}
        placeholder="Co się nie zgadza (opcjonalnie)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        className="rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-hidden"
      />
      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            ["ok", "OK — dane się zgadzają"],
            ["issue", "Uwaga — coś się nie zgadza"],
          ] as Array<[QualityVerdict, string]>
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={row.verdict === value}
            disabled={verdict.isPending}
            onClick={() => save(value)}
            className={cn(
              "min-h-10 rounded-lg border px-3 text-sm font-medium transition-colors pointer-coarse:min-h-11",
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
              row.verdict === value
                ? value === "ok"
                  ? "border-success/30 bg-success-muted text-success-muted-foreground"
                  : "border-warning/30 bg-warning-muted text-warning-muted-foreground"
                : "border-border bg-card text-foreground hover:bg-muted",
            )}
          >
            {label}
          </button>
        ))}
        {row.verdict ? (
          <span className="text-xs text-muted-foreground">Zapisano ocenę.</span>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : null}
    </li>
  );
}

/** Próbka jakości: zadzwoń do kandydata i potwierdź dane z rozmowy praktykanta. */
export function QualitySampleDialog({
  userId,
  name,
  onClose,
}: {
  userId: number | null;
  name: string;
  onClose: () => void;
}) {
  const sample = useTraineeQualitySample(userId);
  return (
    <AppModal
      open={userId != null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={`Próbka jakości — ${name}`}
      description="Zadzwoń do kandydata i potwierdź, że dane w profilu się zgadzają. Nie mamy nagrań rozmów — to jedyna kontrola."
      size="lg"
      footer={
        <Button variant="outline" onClick={onClose}>
          Zamknij
        </Button>
      }
    >
      {sample.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-sm text-destructive">
          Nie udało się wczytać próbki.
          <Button variant="outline" size="sm" onClick={() => sample.refetch()}>
            Ponów
          </Button>
        </div>
      ) : sample.isSuccess && sample.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          W tym tygodniu nie ma jeszcze rozmów do sprawdzenia.
        </p>
      ) : sample.isSuccess && userId != null ? (
        <ul className="flex flex-col gap-3">
          {sample.data.map((row) => (
            <SampleRow key={row.item_id} row={row} userId={userId} />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">Wczytuję próbkę…</p>
      )}
    </AppModal>
  );
}
