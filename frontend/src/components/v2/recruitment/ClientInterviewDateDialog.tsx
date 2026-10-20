"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { warsawToday } from "@/lib/warsaw-date";

const INPUT =
  "h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";
const DURATIONS = [30, 45, 60, 90, 120] as const;

export interface ClientInterviewDate {
  /** Początek rozmowy (ISO, z czasu przeglądarki — jak w oknie terminów od klienta). */
  start: string;
  durationMinutes: number;
}

/**
 * „Kiedy rozmowa u klienta?” przy przesunięciu karty na „Rozmowa u klienta”
 * (20.10.2026). Rozmowę w kalendarzu NEXUSA zakładała dotąd tylko ścieżka
 * „Terminy od klienta”, a karty przesuwa się bez niej — 88 z 99 par w 30
 * dniach nie dostało telefonu po rozmowie ani przypomnienia o pytaniach
 * klienta. Termin stąd uruchamia cały cykl; „Nie znam jeszcze terminu”
 * przesuwa bez niego (po dobie przypomni „Uzupełnij pytania z rozmowy”).
 */
export function ClientInterviewDateDialog({
  open,
  candidateName,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  candidateName: string;
  onCancel: () => void;
  /** `null` = „Nie znam jeszcze terminu” — ruch bez terminu. */
  onConfirm: (value: ClientInterviewDate | null) => void;
}) {
  const [day, setDay] = useState("");
  const [time, setTime] = useState("");
  const [duration, setDuration] = useState<number>(60);
  const [unknown, setUnknown] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDay(warsawToday());
    setTime("");
    setDuration(60);
    setUnknown(false);
    setError(null);
  }, [open]);

  const submit = () => {
    if (unknown) {
      onConfirm(null);
      return;
    }
    if (!day || !time) {
      setError("Podaj dzień i godzinę rozmowy albo zaznacz „Nie znam jeszcze terminu”.");
      return;
    }
    const start = new Date(`${day}T${time}`);
    if (Number.isNaN(start.getTime())) {
      setError("Nie rozpoznaję tej daty — wpisz ją jeszcze raz.");
      return;
    }
    onConfirm({ start: start.toISOString(), durationMinutes: duration });
  };

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => !next && onCancel()}
      title="Kiedy rozmowa u klienta?"
      description={candidateName}
      footer={
        <div className="flex w-full justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="h-10 px-4 text-sm text-muted-foreground hover:text-foreground"
          >
            Anuluj
          </button>
          <button
            type="button"
            onClick={submit}
            data-testid="client-interview-date-submit"
            className="h-10 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            Przesuń
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <fieldset disabled={unknown} className="grid grid-cols-3 gap-2 disabled:opacity-60">
          <div>
            <label htmlFor="client-interview-day" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Dzień
            </label>
            <input
              id="client-interview-day"
              type="date"
              value={day}
              onChange={(e) => setDay(e.target.value)}
              className={INPUT}
            />
          </div>
          <div>
            <label htmlFor="client-interview-time" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Godzina
            </label>
            <input
              id="client-interview-time"
              type="time"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              className={INPUT}
            />
          </div>
          <div>
            <label htmlFor="client-interview-duration" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Długość
            </label>
            <select
              id="client-interview-duration"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
              className={INPUT}
            >
              {DURATIONS.map((m) => (
                <option key={m} value={m}>
                  {m} min
                </option>
              ))}
            </select>
          </div>
        </fieldset>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={unknown}
            onChange={(e) => {
              setUnknown(e.target.checked);
              setError(null);
            }}
            className="h-4 w-4"
          />
          Nie znam jeszcze terminu
        </label>
        <p className="text-xs text-muted-foreground">
          {unknown
            ? "Bez terminu po dobie przypomnimy o pytaniach z rozmowy u klienta."
            : "Po rozmowie przypomnimy o telefonie do kandydata i o pytaniach klienta. Termin zostaje w NEXUSIE — kandydata zaprasza klient."}
        </p>
        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
