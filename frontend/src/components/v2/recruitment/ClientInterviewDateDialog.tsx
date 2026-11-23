"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mail, Plus, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { PasteClientMail } from "@/components/calendar/cycle/PasteClientMail";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import { formatSlot } from "@/lib/interview-cycle";
import {
  isoToLocalInput,
  keepsWindow,
  rowsFromMail,
  type SlotFromMail,
  type SlotRow,
  warningLabel,
} from "@/lib/interview-slot-mail";
import { warsawToday } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";

const INPUT =
  "h-10 w-full rounded-md border border-border bg-card px-3 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";
const DURATIONS = [30, 45, 60, 90, 120] as const;
const MAX_SLOTS = 6;

export interface ClientInterviewDate {
  /** Początek rozmowy (ISO, z czasu przeglądarki — jak w oknie terminów od klienta). */
  start: string;
  durationMinutes: number;
}

/** Terminy od klienta do rekrutera — wniosek po ruchu karty (23.11.2026). */
export interface ClientInterviewSlotsForRecruiter {
  kind: "slots";
  slots: { start: string; window_end?: string }[];
  durationMinutes: number;
  note: string | null;
}

export type ClientInterviewChoice = ClientInterviewDate | ClientInterviewSlotsForRecruiter | null;

type Mode = "slots" | "agreed" | "unknown";

const MODES: { key: Mode; label: string }[] = [
  { key: "slots", label: "Klient podał terminy" },
  { key: "agreed", label: "Termin już ustalony" },
  { key: "unknown", label: "Jeszcze bez terminów" },
];

/**
 * „Kiedy rozmowa u klienta?” przy przesunięciu karty na „Rozmowa u klienta”
 * (20.10.2026). Rozmowę w kalendarzu NEXUSA zakładała dotąd tylko ścieżka
 * „Terminy od klienta”, a karty przesuwa się bez niej — 88 z 99 par w 30
 * dniach nie dostało telefonu po rozmowie ani przypomnienia o pytaniach
 * klienta.
 *
 * Trzy odpowiedzi (decyzja Artura 23.11.2026, zgłoszenie DL): „Klient podał
 * terminy” wysyła je po ruchu rekruterowi (dzwonek i mail „Ustal termin
 * z kandydatem”) — DL nie zna dnia i godziny, ustala je rekruter z kandydatem,
 * a wcześniej musiał wklejać mail klienta drugi raz w „Terminach od klienta”.
 * „Termin już ustalony” zakłada rozmowę od razu, „Jeszcze bez terminów”
 * przesuwa bez niej (po dobie przypomni „Uzupełnij pytania z rozmowy”).
 * Kto nie może wysłać terminów albo sam by je dostał, zaczyna od „Termin
 * już ustalony”.
 */
export function ClientInterviewDateDialog({
  open,
  candidateName,
  candidateId,
  jobId,
  canSendSlots = false,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  candidateName: string;
  candidateId?: number;
  jobId?: number;
  /** Terminy od klienta wysyła DL, HoR albo admin (`_SLOT_OWNER_ROLES`). */
  canSendSlots?: boolean;
  onCancel: () => void;
  /** `null` = „Jeszcze bez terminów” — ruch bez terminu. */
  onConfirm: (value: ClientInterviewChoice) => void;
}) {
  // `null` = jeszcze nie wybrano: domyślna odpowiedź zależy od odbiorcy terminów.
  const [chosenMode, setChosenMode] = useState<Mode | null>(null);
  const [day, setDay] = useState("");
  const [time, setTime] = useState("");
  const [duration, setDuration] = useState<number>(60);
  const [error, setError] = useState<string | null>(null);
  // „Termin już ustalony”: terminy z maila, przy kilku wybiera się jeden (20.10.2026).
  const [mailSlots, setMailSlots] = useState<SlotFromMail[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  // „Klient podał terminy”: wiersze jak w oknie „Terminy od klienta”.
  const [rows, setRows] = useState<SlotRow[]>([{ value: "" }]);
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!open) return;
    setChosenMode(null);
    setDay(warsawToday());
    setTime("");
    setDuration(60);
    setError(null);
    setMailSlots([]);
    setPicked(null);
    setRows([{ value: "" }]);
    setNote("");
  }, [open]);

  const recipient = useQuery({
    queryKey: ["interview-cycle", "slot-recipient", candidateId, jobId],
    queryFn: () => interviewCycleApi.slotRecipient(candidateId as number, jobId as number),
    enabled: open && canSendSlots && candidateId != null && jobId != null,
    retry: false,
  });
  const slotsAllowed = canSendSlots && !recipient.data?.is_you;
  const mode: Mode = chosenMode ?? (slotsAllowed ? "slots" : "agreed");
  const modes = canSendSlots ? MODES : MODES.filter((m) => m.key !== "slots");
  const receiver = recipient.data?.substitute_name ?? recipient.data?.recruiter_name ?? null;

  const chooseMode = (next: Mode) => {
    setChosenMode(next);
    setError(null);
  };

  const pickSlot = (slot: SlotFromMail) => {
    const local = isoToLocalInput(slot.start);
    setDay(local.slice(0, 10));
    // Okno klienta („między 9 a 12”): godzinę w oknie ustala się z kandydatem —
    // nie wpisujemy po cichu początku okna (audyt 22.10, F95).
    setTime(slot.window ? "" : local.slice(11));
    setPicked(slot.start);
    setError(null);
  };

  const pickedWindow = mailSlots.find((s) => s.start === picked && s.window) ?? null;
  const filledRows = rows.filter((r) => r.value);

  const submitSlots = () => {
    if (filledRows.length === 0) {
      setError("Dodaj co najmniej jeden termin od klienta albo wybierz „Jeszcze bez terminów”.");
      return;
    }
    if (filledRows.some((r) => new Date(r.value).getTime() < Date.now())) {
      setError("Termin rozmowy nie może być w przeszłości.");
      return;
    }
    onConfirm({
      kind: "slots",
      slots: filledRows.map((r) => {
        const start = new Date(r.value).toISOString();
        // Okno klienta jedzie dalej, dopóki rozmowa mieści się w nim (jak w „Terminach od klienta”).
        return keepsWindow(r.value, r.windowEnd, duration) ? { start, window_end: r.windowEnd as string } : { start };
      }),
      durationMinutes: duration,
      note: note.trim() || null,
    });
  };

  const submit = () => {
    if (mode === "slots") return submitSlots();
    if (mode === "unknown") {
      onConfirm(null);
      return;
    }
    if (!day || !time) {
      setError("Podaj dzień i godzinę rozmowy albo wybierz „Jeszcze bez terminów”.");
      return;
    }
    const start = new Date(`${day}T${time}`);
    if (Number.isNaN(start.getTime())) {
      setError("Nie rozpoznaję tej daty — wpisz ją jeszcze raz.");
      return;
    }
    onConfirm({ start: start.toISOString(), durationMinutes: duration });
  };

  const submitLabel =
    mode === "slots"
      ? filledRows.length > 1
        ? `Przesuń i wyślij ${filledRows.length} terminy rekruterowi`
        : "Przesuń i wyślij rekruterowi"
      : "Przesuń";

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
            {submitLabel}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <div
          role="radiogroup"
          aria-label="Co wiesz o terminie"
          data-tour="move.client-interview.mode"
          className={cn("grid rounded-lg bg-muted p-1", modes.length === 3 ? "grid-cols-3" : "grid-cols-2")}
        >
          {modes.map((m) => (
            <button
              key={m.key}
              type="button"
              role="radio"
              aria-checked={mode === m.key}
              onClick={() => chooseMode(m.key)}
              className={cn(
                "min-h-8 rounded-md px-2 text-sm",
                mode === m.key
                  ? "bg-card font-semibold text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>

        {mode === "slots" ? (
          <>
            <PasteClientMail
              idPrefix="client-interview-slots"
              onRead={(result) => {
                setRows(rowsFromMail(result).slice(0, MAX_SLOTS));
                const minutes = result.duration_minutes;
                if (minutes && (DURATIONS as readonly number[]).includes(minutes)) setDuration(minutes);
                setError(null);
              }}
            />
            <fieldset className="space-y-2">
              <legend className="mb-1 text-xs font-semibold text-muted-foreground">Terminy od klienta</legend>
              {rows.map((row, i) => {
                const warning = warningLabel(row.warning);
                return (
                  <div key={i} className="space-y-1">
                    <div className="flex items-center gap-2">
                      <input
                        type="datetime-local"
                        aria-label={`Termin ${i + 1}`}
                        value={row.value}
                        onChange={(e) =>
                          setRows((s) =>
                            // Poprawiony ręcznie termin traci ostrzeżenie odczytu — DL go sprawdził.
                            s.map((v, j) => (j === i ? { ...v, value: e.target.value, warning: null } : v)),
                          )
                        }
                        className={INPUT}
                      />
                      {rows.length > 1 ? (
                        <button
                          type="button"
                          aria-label={`Usuń termin ${i + 1}`}
                          onClick={() => setRows((s) => s.filter((_, j) => j !== i))}
                          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      ) : null}
                    </div>
                    {row.quote ? (
                      <p className="text-xs italic text-muted-foreground">
                        „{row.quote}”{row.windowEnd ? " · okno klienta — godzinę ustali rekruter" : ""}
                      </p>
                    ) : null}
                    {warning ? (
                      <p className="rounded-md bg-warning-muted px-2 py-1 text-xs text-warning-muted-foreground">
                        {warning}
                      </p>
                    ) : null}
                  </div>
                );
              })}
              {rows.length < MAX_SLOTS ? (
                <button
                  type="button"
                  onClick={() => setRows((s) => [...s, { value: "" }])}
                  className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline"
                >
                  <Plus className="h-3.5 w-3.5" /> Dodaj termin
                </button>
              ) : null}
            </fieldset>
            <div>
              <span id="client-interview-duration-label" className="mb-1 block text-xs font-semibold text-muted-foreground">
                Czas rozmowy
              </span>
              <div
                role="radiogroup"
                aria-labelledby="client-interview-duration-label"
                className="inline-flex flex-wrap rounded-lg bg-muted p-1"
              >
                {DURATIONS.map((m) => (
                  <button
                    key={m}
                    type="button"
                    role="radio"
                    aria-checked={duration === m}
                    onClick={() => setDuration(m)}
                    className={cn(
                      "h-8 rounded-md px-3 text-sm",
                      duration === m
                        ? "bg-card font-semibold text-foreground shadow-xs"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {m} min
                  </button>
                ))}
              </div>
            </div>
            <input
              aria-label="Notatka dla rekrutera"
              value={note}
              maxLength={1000}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Notatka dla rekrutera (opcjonalnie), np. rozmowa z kamerką"
              className={INPUT}
            />
            <div className="flex items-start gap-2 rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs">
              <Mail className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
              <p>
                {receiver ? <span className="font-semibold">{receiver}</span> : "Rekruter"}
                {recipient.data?.substitute_name ? ` (zastępstwo za ${recipient.data.recruiter_name})` : ""} dostanie
                od razu dzwonek i mail „Ustal termin z kandydatem”. Wybrany termin wróci do Ciebie do potwierdzenia
                u klienta.
              </p>
            </div>
          </>
        ) : null}

        {mode === "agreed" ? (
          <>
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
            <div className="grid grid-cols-3 gap-2">
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
                <label
                  htmlFor="client-interview-duration"
                  className="mb-1 block text-xs font-semibold text-muted-foreground"
                >
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
            </div>
            {pickedWindow ? (
              <p className="text-xs text-muted-foreground">
                Okno klienta {isoToLocalInput(pickedWindow.start).slice(11)}–{isoToLocalInput(pickedWindow.end).slice(11)}{" "}
                — wpisz godzinę ustaloną z kandydatem.
              </p>
            ) : null}
            <p className="text-xs text-muted-foreground">
              Po rozmowie przypomnimy o telefonie do kandydata i o pytaniach klienta. Termin zostaje w NEXUSIE —
              kandydata zaprasza klient.
            </p>
          </>
        ) : null}

        {mode === "unknown" ? (
          <p className="rounded-md bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
            Karta przejdzie dalej bez terminu. Gdy klient przyśle terminy, dodasz je w panelu osoby („Terminy od
            klienta”). Bez terminu po dobie przypomnimy o pytaniach z rozmowy u klienta.
          </p>
        ) : null}

        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
