"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AppModal } from "@/components/ds/AppModal";
import { PrepPeoplePicker } from "@/components/calendar/cycle/PrepPeoplePicker";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  prepMeetingsApi,
  prepQueryKey,
  usePrep,
  usePrepOptions,
  type Prep,
  type PrepUpdateInput,
} from "@/lib/api/prepMeetings";
import {
  candidateLabel,
  formatDayLabel,
  formatTime,
  pairContext,
  type PairInfo,
} from "@/lib/interview-cycle";
import {
  NO_INVITEES,
  invitablePeople,
  inviteesFromAttendees,
  removeUser,
  sameInvitees,
  type Invitees,
} from "@/lib/prep-people";
import {
  defaultPrepStart,
  prepStartInPast,
  prepTimingWarning,
  toLocalInput,
  type PrepInterview,
} from "@/lib/prep-timing";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

const DURATIONS = [30, 45, 60, 90];
const DEFAULT_DURATION = 45;

/** Czyste: długość prepu w minutach (brak końca albo śmieci = 45). */
export function prepDurationMinutes(prep: Pick<Prep, "start" | "end">): number {
  if (!prep.end) return DEFAULT_DURATION;
  const minutes = Math.round(
    (new Date(prep.end).getTime() - new Date(prep.start).getTime()) / 60_000,
  );
  return Number.isFinite(minutes) && minutes > 0 ? minutes : DEFAULT_DURATION;
}

/** Czyste: ciało PATCH tylko z tym, co się zmieniło (pusty obiekt = nic). */
export function prepChanges(
  prep: Pick<Prep, "start" | "end" | "organizer">,
  original: Invitees,
  form: { start: string; duration: number; organizerId: number | null; invitees: Invitees },
): PrepUpdateInput {
  const body: PrepUpdateInput = {};
  const startDate = new Date(form.start);
  const end = new Date(startDate.getTime() + form.duration * 60_000);
  if (
    startDate.getTime() !== new Date(prep.start).getTime() ||
    form.duration !== prepDurationMinutes(prep)
  ) {
    body.start = startDate.toISOString();
    body.end = end.toISOString();
  }
  if (form.organizerId != null && form.organizerId !== prep.organizer?.id) {
    body.organizer_user_id = form.organizerId;
  }
  if (!sameInvitees(original, form.invitees)) {
    body.attendee_user_ids = form.invitees.userIds.filter((id) => id !== form.organizerId);
    body.attendee_emails = form.invitees.emails;
  }
  return body;
}

/**
 * „Zmień prep” — termin, prowadzący, zaproszeni i odwołanie TEGO SAMEGO
 * spotkania (17.10.2026, decyzje D1–D4). Zmienić mogą ludzie pary:
 * prowadzący, Delivery Lead rekrutacji, rekruter kandydata i osoba, która
 * prep zaplanowała (`can_edit` z serwera). Do tej daty prep zmieniał tylko
 * prowadzący — rekruter, który założył Prep 1 w kalendarzu DL-a, nie mógł go
 * przełożyć, gdy kandydat napisał, że termin mu nie pasuje.
 *
 * `mode="late"` — prep wypadł po rozmowie u klienta: termin podpowiada się
 * przed nią (stary jest z definicji zły). `mode="cancel"` — otwiera od razu
 * potwierdzenie odwołania. Zmiana prowadzącego to odwołanie starego spotkania
 * i nowe zaproszenie — Microsoft nie przenosi spotkania między kalendarzami.
 */
export function ReschedulePrepDialog({
  open,
  onOpenChange,
  eventId,
  pair,
  prepNo,
  interview = null,
  mode = "late",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  eventId: number | null;
  pair: PairInfo | null;
  prepNo: 1 | 2;
  interview?: PrepInterview | null;
  mode?: "late" | "edit" | "cancel";
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const currentUserId = useAuthStore((st) => st.user?.id ?? null);
  const prepQuery = usePrep(open ? eventId : null);
  const prep = prepQuery.data ?? null;
  const options = usePrepOptions(
    open ? (prep?.candidate_id ?? pair?.candidate_id ?? null) : null,
    open ? (prep?.job_id ?? pair?.job_id ?? null) : null,
  );
  const [start, setStart] = useState("");
  const [duration, setDuration] = useState(DEFAULT_DURATION);
  const [organizerId, setOrganizerId] = useState<number | null>(null);
  const [invitees, setInvitees] = useState<Invitees>(NO_INVITEES);
  const [view, setView] = useState<"form" | "cancel">(mode === "cancel" ? "cancel" : "form");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  const original = useMemo(() => inviteesFromAttendees(prep?.attendees), [prep?.attendees]);

  // Formularz startuje z danych TEGO prepu. Prep po rozmowie dostaje termin
  // podpowiedziany przed nią, z jego długością.
  useEffect(() => {
    if (!open || !prep) return;
    const minutes = prepDurationMinutes(prep);
    setDuration(minutes);
    setStart(
      mode === "late"
        ? defaultPrepStart(interview, prepNo, minutes)
        : toLocalInput(new Date(prep.start)),
    );
    setOrganizerId(prep.organizer?.id ?? null);
    setInvitees(inviteesFromAttendees(prep.attendees));
    setView(mode === "cancel" ? "cancel" : "form");
    setComment("");
    setError(null);
    // `interview?.start`, nie obiekt — wołający składa go przy każdym renderze.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, prep?.event_id, prep?.start, prep?.end, mode, prepNo, interview?.start, interview?.end]);

  const refresh = (updated: Prep) => {
    qc.setQueryData(prepQueryKey(updated.event_id), updated);
    qc.invalidateQueries({ queryKey: ["interview-cycle"] });
    qc.invalidateQueries({ queryKey: ["calendar-events"] });
    qc.invalidateQueries({ queryKey: ["calendar-upcoming"] });
    qc.invalidateQueries({ queryKey: ["calendar-conflicts-summary"] });
    // Odznaka rozmowy na Tablicy i w panelu osoby.
    qc.invalidateQueries({ queryKey: ["kanban"] });
  };

  const save = useMutation({
    mutationFn: (body: PrepUpdateInput) => prepMeetingsApi.update(eventId as number, body),
    onSuccess: (updated, body) => {
      refresh(updated);
      const when = `${formatDayLabel(updated.start)}, ${formatTime(updated.start)}`;
      toast.showSuccess(
        body.organizer_user_id != null
          ? `Prep ${prepNo} poprowadzi ${updated.organizer?.name ?? "nowa osoba"} — kandydat dostał odwołanie starego spotkania i nowe zaproszenie.`
          : body.start
            ? `Prep ${prepNo} przełożony na ${when} — kandydat dostał aktualizację zaproszenia.`
            : `Zaproszeni na Prep ${prepNo} zmienieni.`,
      );
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zmienić prepu.")),
  });

  const cancel = useMutation({
    mutationFn: () => prepMeetingsApi.cancel(eventId as number, comment.trim() || null),
    onSuccess: (updated) => {
      refresh(updated);
      toast.showSuccess(`Prep ${prepNo} odwołany — kandydat dostał odwołanie spotkania.`);
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się odwołać prepu.")),
  });

  const people = useMemo(() => invitablePeople(options.data), [options.data]);
  const team = options.data?.team ?? [];
  const organizers = prep?.organizer && !team.some((p) => p.id === prep.organizer?.id)
    ? [prep.organizer, ...team]
    : team;
  const excluded = useMemo(
    () => new Set(organizerId != null ? [organizerId] : []),
    [organizerId],
  );
  const names = useMemo(
    () =>
      Object.fromEntries(
        (prep?.attendees ?? [])
          .filter((a) => a.user_id != null && a.name)
          .map((a) => [a.user_id as number, a.name as string]),
      ),
    [prep?.attendees],
  );

  if (!open || eventId == null) return null;

  const organizerChanged = prep != null && organizerId != null && organizerId !== prep.organizer?.id;
  const newOrganizerName = organizers.find((p) => p.id === organizerId)?.name ?? "";
  const timingWarning = start ? prepTimingWarning(start, duration, interview) : null;
  const startInPast = start ? prepStartInPast(start) : false;
  const durations = DURATIONS.includes(duration)
    ? DURATIONS
    : [...DURATIONS, duration].sort((a, b) => a - b);
  const pending = save.isPending || cancel.isPending;
  const editable = prep != null && prep.can_edit !== false && prep.status !== "cancelled";

  const submit = () => {
    setError(null);
    if (!prep) return;
    if (!start || Number.isNaN(new Date(start).getTime())) {
      setError("Podaj termin prepu.");
      return;
    }
    const body = prepChanges(prep, original, { start, duration, organizerId, invitees });
    if (Object.keys(body).length === 0) {
      onOpenChange(false);
      return;
    }
    save.mutate(body);
  };

  const title =
    view === "cancel" ? `Odwołaj Prep ${prepNo}` : mode === "late" ? `Przełóż Prep ${prepNo}` : `Zmień Prep ${prepNo}`;
  const closeButton = (
    <button
      type="button"
      onClick={() => onOpenChange(false)}
      className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
    >
      {editable ? "Anuluj" : "Zamknij"}
    </button>
  );

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={pair ? `${candidateLabel(pair)} · ${pairContext(pair)}` : undefined}
      footer={
        !editable ? (
          closeButton
        ) : view === "cancel" ? (
          <>
            <button
              type="button"
              onClick={() => (mode === "cancel" ? onOpenChange(false) : setView("form"))}
              className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
            >
              {mode === "cancel" ? "Nie odwołuj" : "Wróć"}
            </button>
            <button
              type="button"
              onClick={() => {
                setError(null);
                cancel.mutate();
              }}
              disabled={pending}
              className="h-9 rounded-md bg-destructive px-4 text-sm font-semibold text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              {cancel.isPending ? "Odwołuję…" : "Odwołaj prep"}
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              onClick={() => {
                setError(null);
                setView("cancel");
              }}
              className="mr-auto h-9 px-2 text-sm font-semibold text-destructive hover:underline"
            >
              Odwołaj prep
            </button>
            {closeButton}
            <button
              type="button"
              onClick={submit}
              disabled={pending}
              className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {save.isPending ? "Zapisuję…" : mode === "late" ? "Przełóż" : "Zapisz zmiany"}
            </button>
          </>
        )
      }
    >
      {prepQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie prepu…</p>
      ) : prepQuery.isError || !prep ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {apiErrorMessage(prepQuery.error, "Nie udało się wczytać prepu.")}
        </p>
      ) : (
        <div className="space-y-4" data-testid="reschedule-prep-form">
          <section className="rounded-lg border border-border p-3 text-sm">
            <p className="font-semibold text-foreground">
              Prep {prep.prep_no} · prowadzi {prep.organizer?.name ?? "—"}
              {prep.scheduled_by && prep.scheduled_by.id !== prep.organizer?.id
                ? ` · założony przez: ${prep.scheduled_by.name}`
                : ""}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Teraz:{" "}
              <span className={cn(prep.status === "cancelled" && "line-through")}>
                {formatDayLabel(prep.start)}, {formatTime(prep.start)}
                {prep.end ? `–${formatTime(prep.end)}` : ""}
              </span>
            </p>
            {interview ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Rozmowa u klienta{interview.tentative ? " (termin jeszcze niepotwierdzony)" : ""}:{" "}
                {formatDayLabel(interview.start)}, {formatTime(interview.start)}
              </p>
            ) : null}
          </section>
          {prep.status === "cancelled" ? (
            <p role="status" className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              Ten prep jest odwołany. Zaplanuj nowy z panelu osoby.
            </p>
          ) : prep.can_edit === false ? (
            <p role="status" className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
              Ten prep mogą zmienić: prowadzący, Delivery Lead rekrutacji, rekruter kandydata
              i osoba, która go zaplanowała.
            </p>
          ) : view === "cancel" ? (
            <div className="space-y-3">
              <p className="text-sm text-foreground">
                Kandydat i zaproszeni dostaną odwołanie od {prep.organizer?.name ?? "prowadzącego"}.
                Krok „Prep{prep.prep_no === 2 ? " 2" : ""}” wróci do zaplanowania.
              </p>
              <div>
                <label htmlFor="cancel-prep-comment" className="mb-1 block text-xs font-semibold text-muted-foreground">
                  Wiadomość w odwołaniu (opcjonalnie)
                </label>
                <textarea
                  id="cancel-prep-comment"
                  rows={2}
                  maxLength={500}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  className={cn(INPUT, "resize-none")}
                />
              </div>
            </div>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
                <div>
                  <label htmlFor="reschedule-prep-start" className="mb-1 block text-xs font-semibold text-muted-foreground">
                    Termin
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
              {organizers.length ? (
                <div>
                  <label htmlFor="reschedule-prep-organizer" className="mb-1 block text-xs font-semibold text-muted-foreground">
                    Prowadzi
                  </label>
                  <select
                    id="reschedule-prep-organizer"
                    value={organizerId ?? ""}
                    onChange={(e) => {
                      const next = Number(e.target.value);
                      setOrganizerId(next);
                      setInvitees((v) => removeUser(v, next));
                    }}
                    className={INPUT}
                  >
                    {organizers.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                        {p.id === prep.organizer?.id ? " (prowadzi teraz)" : ""}
                      </option>
                    ))}
                  </select>
                  {organizerChanged ? (
                    <p className="mt-1 rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
                      Kandydat dostanie odwołanie od {prep.organizer?.name ?? "obecnego prowadzącego"}{" "}
                      i nowe zaproszenie od {newOrganizerName} — Microsoft nie przenosi spotkania
                      między kalendarzami. Transkrypt i ocena pójdą na nową osobę.
                    </p>
                  ) : null}
                </div>
              ) : null}
              <PrepPeoplePicker
                id="reschedule-prep-invitees"
                label="Zaproszeni"
                people={people}
                value={invitees}
                onChange={setInvitees}
                exclude={excluded}
                currentUserId={currentUserId}
                names={names}
              />
              {!organizerChanged ? (
                <p className="text-xs text-muted-foreground">
                  Kandydat i zaproszeni dostaną aktualizację tego samego zaproszenia od{" "}
                  {prep.organizer?.name ?? "prowadzącego"}. Link Teams zostaje.
                </p>
              ) : null}
            </>
          )}
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
