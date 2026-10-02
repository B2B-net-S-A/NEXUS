"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Video } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import ScheduleInterviewModal from "@/components/calendar/ScheduleInterviewModal";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { prepMeetingsApi, usePrepOptions } from "@/lib/api/prepMeetings";
import { candidateLabel, pairContext, type PairInfo } from "@/lib/interview-cycle";
import { renderInvitationPreview } from "@/lib/prep-invitation";
import {
  defaultPrepStart,
  prepStartInPast,
  prepTimingWarning,
  type PrepInterview,
} from "@/lib/prep-timing";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

/** Czyste: organizator podpowiadany przez serwer dla tego prepu (albo brak). */
export function defaultOrganizerId(
  suggested: Record<string, { id: number } | null> | undefined,
  prepNo: 1 | 2,
): number | null {
  return suggested?.[String(prepNo)]?.id ?? null;
}

/**
 * „Zaplanuj Prep 1 / Prep 2” — spotkanie Teams w kalendarzu ORGANIZATORA
 * (Prep 1 → Delivery Lead, Prep 2 → rekruter), z zaproszeniem kandydata
 * i automatyczną transkrypcją. Po spotkaniu NEXUS sam pobierze transkrypt,
 * zapisze notatkę i oceni prep.
 *
 * Gdy integracja z Teams nie jest włączona (serwer: `enabled=false`), okno
 * ustępuje dotychczasowemu zaproszeniu przez połączone konto M365 twórcy.
 *
 * `interview` — rozmowa u klienta, do której robi się prep (runda 10, F08):
 * termin podpowiada się PRZED nią, a nakładanie się albo prep po rozmowie
 * dają ostrzeżenie. Termin jeszcze niepotwierdzony (`tentative`) działa tak
 * samo. Bez rozmowy — jutro, 10:00.
 *
 * Okno pokazuje dokładnie to, co dostanie kandydat (tytuł i treść z serwera),
 * i mówi wprost, w czyim kalendarzu powstaje spotkanie i kto dostaje
 * zaproszenie — 02.10.2026 osoba planująca prep „dla DL” spodziewała się go
 * u siebie.
 */
export function PlanPrepDialog({
  open,
  onOpenChange,
  pair,
  prepNo,
  interview = null,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pair: PairInfo;
  prepNo: 1 | 2;
  interview?: PrepInterview | null;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const options = usePrepOptions(open ? pair.candidate_id : null, open ? pair.job_id : null);
  const [organizerId, setOrganizerId] = useState<number | null>(null);
  const [attendees, setAttendees] = useState<number[]>([]);
  const [start, setStart] = useState(() => defaultPrepStart(interview, prepNo, 45));
  const [duration, setDuration] = useState(45);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Stały identyfikator próby — ponowienie po utracie odpowiedzi nie założy
  // drugiego spotkania (serwer → `transactionId` w Graphie).
  const requestId = useRef<string>("");

  useEffect(() => {
    if (!open) return;
    requestId.current =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random()}`;
    setStart(defaultPrepStart(interview, prepNo, 45));
    setDuration(45);
    setNote("");
    setError(null);
    setAttendees([]);
    // `interview?.start`, nie obiekt — wołający składa go przy każdym renderze.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, prepNo, pair.candidate_id, pair.job_id, interview?.start, interview?.end]);

  useEffect(() => {
    if (options.data) setOrganizerId(defaultOrganizerId(options.data.suggested, prepNo));
  }, [options.data, prepNo]);

  const timingWarning = prepTimingWarning(start, duration, interview);
  const startInPast = prepStartInPast(start);

  const team = useMemo(() => options.data?.team ?? [], [options.data]);
  const others = team.filter((p) => p.id !== organizerId);
  const organizerName = team.find((p) => p.id === organizerId)?.name ?? "";
  const invitation = options.data?.invitation?.[String(prepNo)] ?? null;
  // Serwer wpisuje termin rozmowy do treści tylko, gdy prep jest przed nią.
  const beforeInterview =
    !interview || interview.tentative || new Date(start) < new Date(interview.start);

  const mutation = useMutation({
    mutationFn: () => {
      const startDate = new Date(start);
      const end = new Date(startDate.getTime() + duration * 60_000);
      return prepMeetingsApi.create({
        candidate_id: pair.candidate_id,
        job_id: pair.job_id,
        prep_no: prepNo,
        organizer_user_id: organizerId as number,
        start: startDate.toISOString(),
        end: end.toISOString(),
        attendee_user_ids: attendees,
        note: note.trim() || null,
        client_request_id: requestId.current,
      });
    },
    onSuccess: (prep) => {
      qc.invalidateQueries({ queryKey: ["interview-cycle"] });
      qc.invalidateQueries({ queryKey: ["calendar-events"] });
      toast.showSuccess(
        prep.transcription_setup === "failed"
          ? `Prep ${prepNo} zaplanowany. Transkrypcja nie włączyła się sama — organizator musi ją włączyć w Teams.`
          : `Prep ${prepNo} zaplanowany — zaproszenie z linkiem Teams poszło do kandydata.`,
      );
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zaplanować prepu.")),
  });

  if (!open) return null;

  if (options.data && !options.data.enabled) {
    return (
      <ScheduleInterviewModal
        open
        onOpenChange={onOpenChange}
        candidateId={pair.candidate_id}
        candidateName={candidateLabel(pair)}
        candidateEmail={pair.candidate_email}
        defaultJobId={pair.job_id}
        defaultEventType="prep_call"
        defaultTitle={
          options.data.invitation?.[String(prepNo)]?.title ??
          `Przygotowanie do spotkania z Klientem - ${candidateLabel(pair)}`
        }
        defaultStart={defaultPrepStart(interview, prepNo, 45)}
        prepFor={interview}
      />
    );
  }

  const submit = () => {
    setError(null);
    if (organizerId == null) {
      setError("Wybierz, kto prowadzi prep.");
      return;
    }
    if (!start) {
      setError("Podaj termin prepu.");
      return;
    }
    mutation.mutate();
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Zaplanuj Prep ${prepNo}`}
      description={`${candidateLabel(pair)} · ${pairContext(pair)}`}
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
            disabled={mutation.isPending || options.isPending}
            className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            Zaplanuj w Teams
          </button>
        </>
      }
    >
      {options.isPending ? (
        <p className="text-sm text-muted-foreground">Ładowanie zespołu rekrutacji…</p>
      ) : options.isError ? (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {apiErrorMessage(options.error, "Nie udało się wczytać zespołu rekrutacji.")}
        </p>
      ) : (
        <div className="space-y-4">
          <div>
            <label htmlFor="prep-organizer" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Prowadzi (organizator spotkania)
            </label>
            <select
              id="prep-organizer"
              value={organizerId ?? ""}
              onChange={(e) => setOrganizerId(e.target.value ? Number(e.target.value) : null)}
              className={INPUT}
            >
              <option value="">Wybierz osobę</option>
              {team.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {options.data?.suggested?.[String(prepNo)]?.id === p.id ? " (podpowiedź)" : ""}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-muted-foreground">
              Spotkanie powstanie w kalendarzu tej osoby (Outlook i Teams). Zaproszenie dostanie
              kandydat i osoby zaznaczone niżej.
            </p>
          </div>
          {others.length > 0 ? (
            <fieldset>
              <legend className="mb-1 text-xs font-semibold text-muted-foreground">
                Zaproś też z zespołu (opcjonalnie)
              </legend>
              <div className="flex flex-wrap gap-2">
                {others.map((p) => {
                  const checked = attendees.includes(p.id);
                  return (
                    <label
                      key={p.id}
                      className={cn(
                        "inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs",
                        checked ? "border-primary bg-primary/10 text-primary" : "border-border",
                      )}
                    >
                      <input
                        type="checkbox"
                        className="sr-only"
                        checked={checked}
                        onChange={() =>
                          setAttendees((a) =>
                            checked ? a.filter((id) => id !== p.id) : [...a, p.id],
                          )
                        }
                      />
                      {p.name}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
            <div>
              <label htmlFor="prep-start" className="mb-1 block text-xs font-semibold text-muted-foreground">
                Termin
              </label>
              <input
                id="prep-start"
                type="datetime-local"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className={INPUT}
              />
            </div>
            <div>
              <label htmlFor="prep-duration" className="mb-1 block text-xs font-semibold text-muted-foreground">
                Czas
              </label>
              <select
                id="prep-duration"
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className={INPUT}
              >
                {[30, 45, 60, 90].map((m) => (
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
              data-testid="prep-past-warning"
              className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              Ten termin już minął. Sprawdź datę i godzinę — kandydat dostałby zaproszenie na
              spotkanie w przeszłości.
            </p>
          ) : null}
          {timingWarning ? (
            <p
              role="status"
              data-testid="prep-timing-warning"
              className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground"
            >
              {timingWarning}
            </p>
          ) : null}
          <div>
            <label htmlFor="prep-note" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Dopisek do zaproszenia (opcjonalnie)
            </label>
            <textarea
              id="prep-note"
              rows={2}
              maxLength={2000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className={cn(INPUT, "resize-none")}
            />
          </div>
          {invitation ? (
            <section
              aria-label="Podgląd zaproszenia"
              data-testid="prep-invitation-preview"
              className="rounded-lg border border-border p-3 text-xs"
            >
              <h3 className="mb-1 font-semibold text-muted-foreground">Kandydat dostanie</h3>
              <p className="text-sm font-semibold text-foreground">{invitation.title}</p>
              <p className="mt-2 whitespace-pre-line text-foreground">
                {renderInvitationPreview(invitation, {
                  note,
                  organizer: organizerName || "(prowadzący)",
                  beforeInterview,
                })}
              </p>
              <p className="mt-2 border-t border-border pt-2 italic text-muted-foreground">
                {options.data?.notice}
              </p>
            </section>
          ) : null}
          <div className="flex gap-2 rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
            <Video className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            <div className="space-y-1">
              <p className="font-semibold text-foreground">
                {options.data?.auto_transcribe
                  ? "Transkrypcja włączy się automatycznie."
                  : "Włącz transkrypcję w Teams na początku rozmowy."}{" "}
                Po spotkaniu NEXUS zapisze notatkę i oceni prep.
              </p>
              {invitation ? null : (
                <p>Kandydat dostanie w zaproszeniu informację: „{options.data?.notice}”</p>
              )}
            </div>
          </div>
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
