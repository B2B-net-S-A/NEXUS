"use client";

/**
 * Okno „Follow-up: <kandydat>” (0372) — zapis wyniku telefonu, gdy klient
 * milczy. Po lewej ściąga na rozmowę: WSZYSTKIE procesy, w których czekamy na
 * klienta, z ostatnią wiadomością od właściciela każdego z nich (żeby
 * dzwoniący nie obiecał czegoś, czego tamten proces już nie obejmuje). Po
 * prawej wynik — kolejną rundę liczy serwer.
 *
 * Makieta: https://claude.ai/artifact/E3rjEeFPRqp2RFTo3cQunj (B).
 */

import { useEffect, useState } from "react";

import CallDetailsDialog from "@/components/calls/CallDetailsDialog";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import api, { type Call } from "@/lib/api";
import {
  useCandidateFollowup,
  useRecordFollowupOutcome,
  useScheduleFollowupMeeting,
  type FollowupTeamsTranscript,
  type FollowupDetail,
  type FollowupOutcome,
  type FollowupProcessFlag,
  type FollowupRow,
  type FollowupTeamsMeeting,
} from "@/lib/api/candidateFollowups";
import {
  HISTORY_OUTCOME_LABEL,
  OUTCOME_OPTIONS,
  addDaysIso,
  callerReasonSentence,
  columnLabel,
  followupDueLabel,
  followupTone,
  lastContactLabel,
  nextStepSentence,
  shortDate,
  shortPersonName,
  todayInBusinessTz,
} from "@/lib/candidate-followup";
import { cn } from "@/lib/utils";

const TONE_CLASS = {
  danger: "bg-destructive/10 text-destructive",
  warning: "bg-warning-muted text-warning-muted-foreground",
  neutral: "bg-muted text-muted-foreground",
} as const;

const MAX_CALLBACK_DAYS = 60;

export function FollowupDuePill({ row }: { row: Pick<FollowupRow, "state" | "overdue_days" | "due_on"> }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-xs font-medium",
        TONE_CLASS[followupTone(row.state)],
      )}
    >
      {followupDueLabel(row)}
    </span>
  );
}

function ProcessList({ row }: { row: FollowupRow }) {
  return (
    <ul className="space-y-2">
      {row.processes.map((p) => (
        <li key={p.job_id} className="rounded-lg border border-border px-3 py-2">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="min-w-0 text-sm font-medium">
              {p.client_name ? `${p.client_name} · ` : ""}
              {p.job_title}
            </p>
            <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
              {columnLabel(p.column)}
            </span>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            CV wysłane {shortDate(p.sent_at)}
            {p.owner_name ? ` · prowadzi ${p.owner_name}` : ""} · klient milczy {p.silent_days}{" "}
            {p.silent_days === 1 ? "dzień" : "dni"}
          </p>
          <p className="mt-1.5 rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground">
            {p.last_note ? (
              <>
                <span className="font-medium text-foreground">
                  {p.last_note_by ? shortPersonName(p.last_note_by) : "Notatka"}
                  {p.last_note_at ? `, ${shortDate(p.last_note_at)}` : ""}:
                </span>{" "}
                „{p.last_note}”
              </>
            ) : (
              "Brak notatek w tym procesie."
            )}
          </p>
        </li>
      ))}
    </ul>
  );
}

function History({ detail, onCall }: { detail: FollowupDetail; onCall: (callId: number) => void }) {
  if (detail.history.length === 0) return null;
  return (
    <div className="mt-4">
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Ostatnie follow-upy
      </h4>
      <ul className="space-y-1 text-xs text-muted-foreground">
        {detail.history.map((h) => (
          <li key={`${h.created_at}-${h.outcome}`}>
            <span className="tabular-nums">{shortDate(h.created_at)}</span> ·{" "}
            {shortPersonName(h.user_name) || "ktoś z zespołu"} ·{" "}
            {HISTORY_OUTCOME_LABEL[h.outcome] ?? h.outcome}
            {h.callback_on ? ` (${shortDate(h.callback_on)})` : ""}
            {h.call_id && (
              <button type="button" className="ml-2 text-primary underline" onClick={() => onCall(h.call_id!)}>
                {h.has_transcript ? "Transkrypt" : h.has_recording ? "Nagranie" : "Rozmowa CloudTalk"}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MeetingList({ meetings, onTranscript }: { meetings: FollowupTeamsMeeting[]; onTranscript: (id: number) => void }) {
  if (meetings.length === 0) return null;
  return (
    <div className="mt-3 space-y-2 text-xs">
      <h4 className="font-semibold">Spotkania Teams</h4>
      {meetings.map((meeting) => (
        <div key={meeting.id} className="border-t border-border pt-2">
          <span>{new Date(meeting.start).toLocaleString("pl-PL")}</span>
          {meeting.join_url && <a href={meeting.join_url} target="_blank" rel="noreferrer" className="ml-2 text-primary underline">Dołącz w Teams</a>}
          {meeting.recording_url && <a href={meeting.recording_url} target="_blank" rel="noreferrer" className="ml-2 text-primary underline">Nagranie</a>}
          {meeting.transcript_status === "fetched" ? (
            <button type="button" onClick={() => onTranscript(meeting.id)} className="ml-2 text-primary underline">Transkrypt</button>
          ) : <span className="ml-2 text-muted-foreground">Transkrypt: {meeting.transcript_status}</span>}
          {meeting.transcription_setup === "failed" && <p className="mt-1 text-destructive">Włącz nagrywanie i transkrypcję ręcznie w Teams.</p>}
        </div>
      ))}
    </div>
  );
}

export interface CandidateFollowupDialogProps {
  candidateId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CandidateFollowupDialog({
  candidateId,
  open,
  onOpenChange,
}: CandidateFollowupDialogProps) {
  const { showSuccess, showError } = useToast();
  const detail = useCandidateFollowup(candidateId, open);
  const record = useRecordFollowupOutcome(candidateId ?? 0);
  const schedule = useScheduleFollowupMeeting(candidateId ?? 0);
  const [outcome, setOutcome] = useState<FollowupOutcome>("connected");
  const [note, setNote] = useState("");
  const [callbackOn, setCallbackOn] = useState("");
  const [flags, setFlags] = useState<Record<number, FollowupProcessFlag>>({});
  const [openCall, setOpenCall] = useState<Call | null>(null);
  const [meetingStart, setMeetingStart] = useState("");
  const [meetingEnd, setMeetingEnd] = useState("");
  const [meetingRequestId, setMeetingRequestId] = useState("");
  const [transcript, setTranscript] = useState<FollowupTeamsTranscript | null>(null);

  const scheduleMeeting = () => {
    if (!candidateId || !meetingStart || !meetingEnd) return;
    const start = new Date(meetingStart);
    const end = new Date(meetingEnd);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start <= new Date() || end <= start) {
      showError("Podaj przyszły początek i późniejszy koniec spotkania.");
      return;
    }
    const requestId = meetingRequestId || crypto.randomUUID();
    setMeetingRequestId(requestId);
    schedule.mutate(
      { start: start.toISOString(), end: end.toISOString(), client_request_id: requestId },
      {
        onSuccess: () => {
          setMeetingRequestId("");
          setMeetingStart("");
          setMeetingEnd("");
          showSuccess("Spotkanie Teams utworzone. Zaproszenie wysłano do kandydata.");
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zaplanować spotkania Teams.")),
      },
    );
  };

  const showTranscript = async (meetingId: number) => {
    if (!candidateId) return;
    try {
      const response = await api.get<FollowupTeamsTranscript>(
        `/api/candidate-followups/candidates/${candidateId}/teams-meetings/${meetingId}/transcript`,
      );
      setTranscript(response.data);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wczytać transkryptu."));
    }
  };

  const showCall = async (id: number) => {
    if (candidateId == null) return;
    try {
      const response = await api.get<Call>(`/api/candidates/${candidateId}/calls/${id}`);
      setOpenCall(response.data);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się wczytać rozmowy."));
    }
  };

  useEffect(() => {
    if (!open) {
      setOutcome("connected");
      setNote("");
      setCallbackOn("");
      setFlags({});
      setOpenCall(null);
      setTranscript(null);
      setMeetingStart("");
      setMeetingEnd("");
      setMeetingRequestId("");
    }
  }, [open]);

  const row = detail.data?.followup ?? null;
  const today = todayInBusinessTz();
  const noteRequired = outcome === "changed";
  const invalid =
    (noteRequired && note.trim() === "") || (outcome === "callback" && callbackOn === "");

  const submit = () => {
    if (!row || invalid) return;
    record.mutate(
      {
        outcome,
        note: note.trim() || null,
        callback_on: outcome === "callback" ? callbackOn : null,
        processes: outcome === "changed" ? flags : {},
      },
      {
        onSuccess: (data) => {
          const next = data.followup?.due_on;
          showSuccess(
            next
              ? `Zapisano. Następny follow-up: ${shortDate(next)}.`
              : "Zapisano. Kandydat nie czeka już na odpowiedź klienta.",
          );
          onOpenChange(false);
        },
        onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać wyniku telefonu.")),
      },
    );
  };

  return (
    <>
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="2xl" className="flex max-h-[92dvh] flex-col p-0" aria-describedby="followup-desc">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-3 pr-14">
          <div className="min-w-0 space-y-0.5">
            <DialogTitle className="text-base font-semibold">
              Follow-up: {row?.candidate_name ?? "kandydat"}
            </DialogTitle>
            <DialogDescription id="followup-desc" className="text-xs text-muted-foreground">
              {row ? (
                <>
                  {row.phone ? (
                    <span className="select-all font-mono text-foreground">{row.phone}</span>
                  ) : (
                    "Brak telefonu w profilu"
                  )}{" "}
                  · {lastContactLabel(row)}
                </>
              ) : (
                "Telefon do kandydata, gdy klient milczy."
              )}
            </DialogDescription>
          </div>
          {row && <FollowupDuePill row={row} />}
        </div>

        {detail.isError ? (
          <div className="px-5 py-6 text-sm">
            <p>{apiErrorMessage(detail.error, "Nie udało się wczytać follow-upu.")}</p>
            <Button size="sm" variant="outline" className="mt-3" onClick={() => detail.refetch()}>
              Ponów
            </Button>
          </div>
        ) : !detail.isSuccess ? (
          <p className="px-5 py-6 text-sm text-muted-foreground">Wczytywanie…</p>
        ) : !row ? (
          <div className="overflow-y-auto px-5 py-6 text-sm">
            <p>Ten kandydat nie czeka już na odpowiedź klienta — follow-up nie jest potrzebny.</p>
            <MeetingList meetings={detail.data.meetings ?? []} onTranscript={showTranscript} />
            <History detail={detail.data} onCall={showCall} />
          </div>
        ) : (
          <div className="grid min-h-0 flex-1 overflow-y-auto md:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <div className="border-b border-border px-5 py-4 md:border-b-0 md:border-r">
              <h3 className="mb-2 text-sm font-semibold">
                Czeka na klienta w {row.processes.length}{" "}
                {row.processes.length === 1 ? "procesie" : "procesach"}
              </h3>
              <ProcessList row={row} />
              <p className="mt-3 border-l-2 border-primary/30 pl-2.5 text-xs text-muted-foreground">
                Powiedz, że kandydat dalej jest w procesach i czekamy na odpowiedź klientów.
                Zapytaj, czy coś się zmieniło: dostępność, stawka, inne oferty.
              </p>
              <p className="mt-2 text-xs text-muted-foreground">
                Dzwoni {row.caller_name ?? "—"}: {callerReasonSentence(row)}.
              </p>
              <div className="mt-4 space-y-2 rounded-lg border border-border p-3">
                <h4 className="text-sm font-semibold">Rozmowa w Teams</h4>
                <p className="text-xs text-muted-foreground">Kandydat dostanie zaproszenie Outlook. Spotkanie zostanie nagrane, a transkrypt trafi do NEXUS.</p>
                <label className="block text-xs">Początek
                  <input type="datetime-local" value={meetingStart} onChange={(e) => setMeetingStart(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm" />
                </label>
                <label className="block text-xs">Koniec
                  <input type="datetime-local" value={meetingEnd} onChange={(e) => setMeetingEnd(e.target.value)} className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm" />
                </label>
                <Button size="sm" onClick={scheduleMeeting} disabled={!meetingStart || !meetingEnd || schedule.isPending}>
                  {schedule.isPending ? "Planowanie…" : "Zaplanuj spotkanie Teams"}
                </Button>
                <MeetingList meetings={detail.data?.meetings ?? []} onTranscript={showTranscript} />
              </div>
              {detail.data && <History detail={detail.data} onCall={showCall} />}
            </div>
            <div className="space-y-4 px-5 py-4">
              <fieldset>
                <legend className="mb-2 text-sm font-semibold">Jak poszło?</legend>
                <div className="space-y-1.5">
                  {OUTCOME_OPTIONS.map((opt) => (
                    <label
                      key={opt.value}
                      className={cn(
                        "flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 text-sm",
                        outcome === opt.value ? "border-primary bg-primary/5" : "border-border",
                      )}
                    >
                      <input
                        type="radio"
                        name="followup-outcome"
                        value={opt.value}
                        checked={outcome === opt.value}
                        onChange={() => setOutcome(opt.value)}
                        className="mt-0.5 accent-primary"
                      />
                      <span>
                        {opt.label}
                        <span className="block text-xs text-muted-foreground">{opt.hint}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {outcome === "changed" && row.processes.length > 0 && (
                <fieldset>
                  <legend className="mb-1.5 text-sm font-semibold">Co z każdym procesem?</legend>
                  <div className="space-y-1.5 text-sm">
                    {row.processes.map((p) => (
                      <label key={p.job_id} className="flex flex-wrap items-center justify-between gap-2">
                        <span className="min-w-0 truncate">{p.client_name ?? p.job_title}</span>
                        <select
                          value={flags[p.job_id] ?? "interested"}
                          onChange={(e) =>
                            setFlags((prev) => ({
                              ...prev,
                              [p.job_id]: e.target.value as FollowupProcessFlag,
                            }))
                          }
                          className="rounded-md border border-border bg-background px-2 py-1 text-sm"
                          aria-label={`Proces ${p.client_name ?? p.job_title}`}
                        >
                          <option value="interested">dalej zainteresowany</option>
                          <option value="withdrawing">rezygnuje</option>
                        </select>
                      </label>
                    ))}
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    Właściciel procesu dostanie powiadomienie. Etap nie zmieni się sam.
                  </p>
                </fieldset>
              )}

              {outcome === "callback" && (
                <div>
                  <label htmlFor="followup-callback" className="mb-1 block text-sm font-semibold">
                    Kiedy oddzwonić?
                  </label>
                  <input
                    id="followup-callback"
                    type="date"
                    min={today}
                    max={addDaysIso(today, MAX_CALLBACK_DAYS)}
                    value={callbackOn}
                    onChange={(e) => setCallbackOn(e.target.value)}
                    className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  />
                </div>
              )}

              {(outcome === "connected" || outcome === "changed") && (
                <div>
                  <label htmlFor="followup-note" className="mb-1 block text-sm font-semibold">
                    {noteRequired ? "Co się zmieniło?" : "Notatka (opcjonalnie)"}
                  </label>
                  <Textarea
                    id="followup-note"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    rows={3}
                    maxLength={4000}
                    placeholder="np. Dostępny od 01.11, stawka bez zmian."
                  />
                </div>
              )}

              <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
                {nextStepSentence(outcome, callbackOn || null)}
              </p>
            </div>
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          {row && (
            <Button onClick={submit} disabled={invalid || record.isPending}>
              {record.isPending ? "Zapisywanie…" : "Zapisz"}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
    <CallDetailsDialog call={openCall} open={openCall !== null} onOpenChange={(value) => !value && setOpenCall(null)} />
    <Dialog open={transcript !== null} onOpenChange={(value) => !value && setTranscript(null)}>
      <DialogContent size="2xl" aria-describedby="followup-transcript-desc">
        <DialogTitle>Transkrypt rozmowy Teams</DialogTitle>
        <DialogDescription id="followup-transcript-desc">Zapis rozmowy z kandydatem w NEXUS.</DialogDescription>
        <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap text-sm">{transcript?.text}</pre>
      </DialogContent>
    </Dialog>
    </>
  );
}
