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
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

function nextWorkdayAt(hour: number): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  while (d.getDay() === 0 || d.getDay() === 6) d.setDate(d.getDate() + 1);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(hour)}:00`;
}

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
 */
export function PlanPrepDialog({
  open,
  onOpenChange,
  pair,
  prepNo,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pair: PairInfo;
  prepNo: 1 | 2;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const options = usePrepOptions(open ? pair.candidate_id : null, open ? pair.job_id : null);
  const [organizerId, setOrganizerId] = useState<number | null>(null);
  const [attendees, setAttendees] = useState<number[]>([]);
  const [start, setStart] = useState(nextWorkdayAt(10));
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
    setStart(nextWorkdayAt(10));
    setDuration(45);
    setNote("");
    setError(null);
    setAttendees([]);
  }, [open, prepNo, pair.candidate_id, pair.job_id]);

  useEffect(() => {
    if (options.data) setOrganizerId(defaultOrganizerId(options.data.suggested, prepNo));
  }, [options.data, prepNo]);

  const team = useMemo(() => options.data?.team ?? [], [options.data]);
  const others = team.filter((p) => p.id !== organizerId);

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
        defaultTitle={`Prep ${prepNo}: ${candidateLabel(pair)}`}
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
          </div>
          {others.length > 0 ? (
            <fieldset>
              <legend className="mb-1 text-xs font-semibold text-muted-foreground">
                Dołączają też (opcjonalnie)
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
          <div>
            <label htmlFor="prep-note" className="mb-1 block text-xs font-semibold text-muted-foreground">
              Wiadomość w zaproszeniu (opcjonalnie)
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
          <div className="flex gap-2 rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
            <Video className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
            <div className="space-y-1">
              <p className="font-semibold text-foreground">
                {options.data?.auto_transcribe
                  ? "Transkrypcja włączy się automatycznie."
                  : "Włącz transkrypcję w Teams na początku rozmowy."}{" "}
                Po spotkaniu NEXUS zapisze notatkę i oceni prep.
              </p>
              <p>Kandydat dostanie w zaproszeniu informację: „{options.data?.notice}”</p>
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
