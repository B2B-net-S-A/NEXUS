"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { isOutlookEvent, type CalendarEvent } from "@/components/calendar/calendar-config";
import { useToast } from "@/components/Toast";
import { calendarApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  candidateLabel,
  formatDayLabel,
  formatTime,
  pairContext,
  type PairInfo,
} from "@/lib/interview-cycle";
import {
  defaultPrepStart,
  prepStartInPast,
  prepTimingWarning,
  type PrepInterview,
} from "@/lib/prep-timing";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

const DURATIONS = [30, 45, 60, 90];
const DEFAULT_DURATION = 45;

/** Czyste: długość spotkania w minutach (brak końca albo śmieci = 45). */
export function eventDurationMinutes(event: Pick<CalendarEvent, "start_time" | "end_time">): number {
  if (!event.end_time) return DEFAULT_DURATION;
  const minutes = Math.round(
    (new Date(event.end_time).getTime() - new Date(event.start_time).getTime()) / 60_000,
  );
  return Number.isFinite(minutes) && minutes > 0 ? minutes : DEFAULT_DURATION;
}

export function rescheduleQueryKey(eventId: number | null) {
  return ["calendar-event", eventId] as const;
}

/**
 * „Przełóż” prep, który wypadł po rozmowie u klienta: to samo spotkanie,
 * nowy termin. Tytuł, kandydat, rekrutacja, organizator, uczestnicy i link
 * Teams zostają — zmienia się tylko data i godzina (PATCH istniejącego
 * wydarzenia; serwer przepycha zmianę do Outlooka organizatora, więc kandydat
 * dostaje aktualizację zaproszenia, a nie drugie).
 *
 * Do 04.10.2026 przycisk prowadził na widok Tydzień — tam klik w siatkę
 * otwierał puste „Nowe wydarzenie” i ludzie zakładali drugi prep.
 */
export function ReschedulePrepDialog({
  open,
  onOpenChange,
  eventId,
  pair,
  prepNo,
  interview = null,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  pair: PairInfo | null;
  prepNo: 1 | 2;
  interview?: PrepInterview | null;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const eventQuery = useQuery<CalendarEvent>({
    queryKey: rescheduleQueryKey(eventId),
    queryFn: () => calendarApi.getEvent(eventId as number).then((r) => r.data as CalendarEvent),
    enabled: open && eventId != null,
  });
  const event = eventQuery.data ?? null;
  const [start, setStart] = useState("");
  const [duration, setDuration] = useState(DEFAULT_DURATION);
  const [error, setError] = useState<string | null>(null);

  // Formularz startuje z danych TEGO prepu: długość z wydarzenia, termin
  // podpowiadany przed rozmową (stary termin jest po niej — z definicji zły).
  useEffect(() => {
    if (!open || !event) return;
    const minutes = eventDurationMinutes(event);
    setDuration(minutes);
    setStart(defaultPrepStart(interview, prepNo, minutes));
    setError(null);
    // `interview?.start`, nie obiekt — wołający składa go przy każdym renderze.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, event?.id, event?.start_time, event?.end_time, prepNo, interview?.start, interview?.end]);

  const mutation = useMutation({
    mutationFn: () => {
      const startDate = new Date(start);
      const end = new Date(startDate.getTime() + duration * 60_000);
      return calendarApi
        .updateEvent(eventId as number, {
          start_time: startDate.toISOString(),
          end_time: end.toISOString(),
        })
        .then((r) => r.data as CalendarEvent);
    },
    onSuccess: (updated) => {
      qc.setQueryData(rescheduleQueryKey(eventId), updated);
      qc.invalidateQueries({ queryKey: ["interview-cycle"] });
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      qc.invalidateQueries({ queryKey: ["calendar-upcoming"] });
      qc.invalidateQueries({ queryKey: ["calendar-conflicts-summary"] });
      toast.showSuccess(
        isOutlookEvent(updated)
          ? `Prep ${prepNo} przełożony na ${formatDayLabel(updated.start_time)}, ${formatTime(updated.start_time)} — uczestnicy dostali nowy termin z Outlooka.`
          : `Prep ${prepNo} przełożony na ${formatDayLabel(updated.start_time)}, ${formatTime(updated.start_time)}.`,
      );
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się przełożyć prepu.")),
  });

  if (!open || eventId == null) return null;

  const timingWarning = start ? prepTimingWarning(start, duration, interview) : null;
  const startInPast = start ? prepStartInPast(start) : false;
  const durations = DURATIONS.includes(duration) ? DURATIONS : [...DURATIONS, duration].sort((a, b) => a - b);

  const submit = () => {
    setError(null);
    if (!start || Number.isNaN(new Date(start).getTime())) {
      setError("Podaj nowy termin prepu.");
      return;
    }
    mutation.mutate();
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Przełóż Prep ${prepNo}`}
      description={pair ? `${candidateLabel(pair)} · ${pairContext(pair)}` : undefined}
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
          >
            Anuluj
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={mutation.isPending || !event}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {mutation.isPending ? "Zapisuję…" : "Przełóż"}
          </button>
        </>
      }
    >
      {eventQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie prepu…</p>
      ) : eventQuery.isError || !event ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {apiErrorMessage(eventQuery.error, "Nie udało się wczytać prepu.")}
        </p>
      ) : (
        <div className="space-y-4" data-testid="reschedule-prep-form">
          <section className="rounded-lg border border-border p-3 text-sm">
            <p className="font-semibold text-foreground">{event.title}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Teraz:{" "}
              <span className="line-through">
                {formatDayLabel(event.start_time)}, {formatTime(event.start_time)}
                {event.end_time ? `–${formatTime(event.end_time)}` : ""}
              </span>
            </p>
            {interview ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Rozmowa u klienta{interview.tentative ? " (termin jeszcze niepotwierdzony)" : ""}:{" "}
                {formatDayLabel(interview.start)}, {formatTime(interview.start)}
              </p>
            ) : null}
            <p className="mt-2 text-xs text-muted-foreground">
              Tytuł, kandydat, uczestnicy i link Teams zostają bez zmian — zmienia się tylko termin.
            </p>
          </section>
          <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
            <div>
              <label htmlFor="reschedule-prep-start" className="mb-1 block text-xs font-semibold text-muted-foreground">
                Nowy termin
              </label>
              <input
                id="reschedule-prep-start"
                type="datetime-local"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className={INPUT}
              />
            </div>
            <div>
              <label htmlFor="reschedule-prep-duration" className="mb-1 block text-xs font-semibold text-muted-foreground">
                Czas
              </label>
              <select
                id="reschedule-prep-duration"
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className={INPUT}
              >
                {durations.map((m) => (
                  <option key={m} value={m}>
                    {m} min
                  </option>
                ))}
              </select>
            </div>
          </div>
          {startInPast ? (
            <p
              role="status"
              className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              Ten termin już minął. Sprawdź datę i godzinę.
            </p>
          ) : null}
          {timingWarning ? (
            <p
              role="status"
              data-testid="reschedule-prep-timing-warning"
              className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              {timingWarning}
            </p>
          ) : null}
          {error ? (
            <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
      )}
    </AppModal>
  );
}
