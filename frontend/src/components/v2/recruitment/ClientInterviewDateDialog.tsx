"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { PasteClientMail } from "@/components/calendar/cycle/PasteClientMail";
import { formatSlot } from "@/lib/interview-cycle";
import { isoToLocalInput, type SlotFromMail, warningLabel } from "@/lib/interview-slot-mail";
import { warsawToday } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";

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
  // Terminy z wklejonego maila: przy kilku wybiera się jeden (20.10.2026).
  const [mailSlots, setMailSlots] = useState<SlotFromMail[]>([]);
  const [picked, setPicked] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDay(warsawToday());
    setTime("");
    setDuration(60);
    setUnknown(false);
    setError(null);
    setMailSlots([]);
    setPicked(null);
  }, [open]);

  const pickSlot = (slot: SlotFromMail) => {
    const local = isoToLocalInput(slot.start);
    setDay(local.slice(0, 10));
    // Okno klienta („między 9 a 12”): godzinę w oknie ustala się z kandydatem —
    // nie wpisujemy po cichu początku okna (audyt 22.10, F95).
    setTime(slot.window ? "" : local.slice(11));
    setPicked(slot.start);
    setUnknown(false);
    setError(null);
  };

  const pickedWindow = mailSlots.find((s) => s.start === picked && s.window) ?? null;

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
        <PasteClientMail
          idPrefix="client-interview"
          onRead={(result) => {
            setMailSlots(result.slots);
            const minutes = result.duration_minutes;
            if (minutes && (DURATIONS as readonly number[]).includes(minutes)) setDuration(minutes);
            if (result.slots.length === 1) pickSlot(result.slots[0]);
          }}
        />
        {/* Także przy jednym terminie: cytat i ostrzeżenie odczytu muszą być widoczne (F95). */}
        {mailSlots.length > 0 ? (
          <div role="radiogroup" aria-label="Terminy z maila" className="space-y-1.5">
            <p className="text-xs font-semibold text-muted-foreground">
              {mailSlots.length > 1 ? "Który termin wybrał kandydat?" : "Termin z maila"}
            </p>
            {mailSlots.map((slot) => {
              const warning = warningLabel(slot.warning);
              return (
                <button
                  key={slot.start}
                  type="button"
                  role="radio"
                  aria-checked={picked === slot.start}
                  onClick={() => pickSlot(slot)}
                  className={cn(
                    "flex w-full flex-col items-start rounded-md border px-3 py-2 text-left text-sm",
                    picked === slot.start ? "border-primary bg-primary/5" : "border-border hover:bg-muted",
                  )}
                >
                  <span className="font-semibold">{formatSlot({ start: slot.start, end: slot.end })}</span>
                  <span className="text-xs italic text-muted-foreground">„{slot.quote}”</span>
                  {warning ? <span className="text-xs text-warning-muted-foreground">{warning}</span> : null}
                </button>
              );
            })}
          </div>
        ) : null}
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
        {pickedWindow && !unknown ? (
          <p className="text-xs text-muted-foreground">
            Okno klienta {isoToLocalInput(pickedWindow.start).slice(11)}–{isoToLocalInput(pickedWindow.end).slice(11)} —
            wpisz godzinę ustaloną z kandydatem.
          </p>
        ) : null}
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
