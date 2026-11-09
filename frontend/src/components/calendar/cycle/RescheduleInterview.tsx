"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { interviewCycleApi, useInterviewEvent } from "@/lib/api/interviewCycle";
import {
  candidateLabel,
  formatDayLabel,
  formatTime,
  pairContext,
  type PairInfo,
} from "@/lib/interview-cycle";
import { prepStartInPast, toLocalInput } from "@/lib/prep-timing";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

const DURATIONS = [30, 45, 60, 90, 120];
const DEFAULT_DURATION = 60;

function durationMinutes(start: string, end: string | null): number {
  if (!end) return DEFAULT_DURATION;
  const minutes = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60_000);
  return Number.isFinite(minutes) && minutes > 0 ? minutes : DEFAULT_DURATION;
}

/**
 * „Zmień termin” przy rozmowie u klienta — widzą ją ludzie pary
 * (`can_reschedule` z serwera), tak samo jak „Zmień” przy prepie.
 */
export function InterviewRescheduleButton({
  eventId,
  onEdit,
  className,
}: {
  eventId: number;
  onEdit: () => void;
  className?: string;
}) {
  const event = useInterviewEvent(eventId);
  if (!event.data?.can_reschedule) return null;
  return (
    <button
      type="button"
      data-tour="calendar.interview.reschedule"
      onClick={onEdit}
      className={cn(
        "h-8 rounded-md border border-border bg-card px-2.5 text-xs font-semibold hover:bg-muted",
        className,
      )}
    >
      Zmień termin
    </button>
  );
}

/**
 * Klient przełożył rozmowę (zgłoszenie 04.11.2026). Nowy termin dostaje TO SAMO
 * wydarzenie, więc prepy, telefon po rozmowie i debrief zostają przy tej rundzie.
 * Do tej daty panel pozwalał przełożyć tylko prep, a prep po starej dacie rozmowy
 * świecił na czerwono „po rozmowie u klienta”.
 */
export function RescheduleInterviewDialog({
  open,
  onOpenChange,
  eventId,
  pair,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  pair: PairInfo | null;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const query = useInterviewEvent(open ? eventId : null);
  const event = query.data ?? null;
  const [start, setStart] = useState("");
  const [duration, setDuration] = useState(DEFAULT_DURATION);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !event) return;
    setStart(toLocalInput(new Date(event.start)));
    setDuration(durationMinutes(event.start, event.end));
    setError(null);
  }, [open, event?.id, event?.start, event?.end]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (body: { start: string; duration_minutes: number }) =>
      interviewCycleApi.rescheduleInterview(eventId as number, body),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ["interview-cycle"] });
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      qc.invalidateQueries({ queryKey: ["calendar-upcoming"] });
      qc.invalidateQueries({ queryKey: ["calendar-conflicts-summary"] });
      // Odznaka rozmowy na Tablicy i w panelu osoby.
      qc.invalidateQueries({ queryKey: ["kanban"] });
      toast.showSuccess(
        `Rozmowa przełożona na ${formatDayLabel(updated.start)}, ${formatTime(updated.start)}. Sprawdź godziny prepów.`,
      );
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zmienić terminu rozmowy.")),
  });

  if (!open || eventId == null) return null;

  const submit = () => {
    setError(null);
    if (!event) return;
    const next = new Date(start);
    if (!start || Number.isNaN(next.getTime())) {
      setError("Podaj nowy termin rozmowy.");
      return;
    }
    const unchanged =
      next.getTime() === new Date(toLocalInput(new Date(event.start))).getTime() &&
      duration === durationMinutes(event.start, event.end);
    if (unchanged) {
      onOpenChange(false);
      return;
    }
    save.mutate({ start: next.toISOString(), duration_minutes: duration });
  };

  const durations = DURATIONS.includes(duration)
    ? DURATIONS
    : [...DURATIONS, duration].sort((a, b) => a - b);
  const closeButton = (
    <button
      type="button"
      onClick={() => onOpenChange(false)}
      className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
    >
      Anuluj
    </button>
  );

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zmień termin rozmowy"
      description={pair ? `${candidateLabel(pair)} · ${pairContext(pair)}` : undefined}
      footer={
        event ? (
          <>
            {closeButton}
            <button
              type="button"
              onClick={submit}
              disabled={save.isPending}
              className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {save.isPending ? "Zapisuję…" : "Przełóż rozmowę"}
            </button>
          </>
        ) : (
          closeButton
        )
      }
    >
      {query.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie rozmowy…</p>
      ) : query.isError || !event ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {apiErrorMessage(query.error, "Nie udało się wczytać rozmowy.")}
        </p>
      ) : (
        <div className="space-y-4" data-testid="reschedule-interview-form">
          <p className="rounded-lg border border-border p-3 text-sm text-muted-foreground">
            Teraz:{" "}
            <span className="font-semibold text-foreground">
              {formatDayLabel(event.start)}, {formatTime(event.start)}
              {event.end ? `–${formatTime(event.end)}` : ""}
            </span>
          </p>
          <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
            <div>
              <label
                htmlFor="reschedule-interview-start"
                className="mb-1 block text-xs font-semibold text-muted-foreground"
              >
                Nowy termin
              </label>
              <input
                id="reschedule-interview-start"
                type="datetime-local"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className={INPUT}
              />
            </div>
            <div>
              <label
                htmlFor="reschedule-interview-duration"
                className="mb-1 block text-xs font-semibold text-muted-foreground"
              >
                Czas
              </label>
              <select
                id="reschedule-interview-duration"
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
          {start && prepStartInPast(start) ? (
            <p
              role="status"
              className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              Ten termin już minął. Sprawdź datę i godzinę.
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            Delivery Lead i rekruter dostaną powiadomienie. Kandydata zaprasza klient, więc o nowym
            terminie powiedz mu sam. Prepy zostają: jeśli wypadną po rozmowie, ekran poprosi o ich
            przełożenie.
          </p>
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
