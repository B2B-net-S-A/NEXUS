"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Ban,
  Briefcase,
  CheckCircle,
  Clock,
  MapPin,
  MessageSquare,
  Pencil,
  User,
  UserCheck,
  Users,
  Video,
  X,
} from "lucide-react";

import { calendarApi, type CalendarCancelOutcome, type CalendarCancelResponse } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { allDayLabel } from "@/lib/calendar-all-day";
import { attendeeAddress, attendeeLabel } from "@/lib/calendar-attendees";
import { htmlToPlainText } from "@/lib/plain-text";
import { ConfirmButton } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { CandidateCombobox, type CandidateChoice } from "@/components/calendar/CandidateCombobox";
import { RecruitmentSelect } from "@/components/calendar/RecruitmentSelect";
import {
  EVENT_TYPE_CONFIG,
  FEEDBACK_EVENT_TYPES,
  REMINDER_OPTIONS,
  RecordingBlock,
  STATUS_CONFIG,
  isOutlookEvent,
  type CalendarEvent,
} from "@/components/calendar/calendar-config";

const CONFIRMATION_SOURCE_LABELS: Record<string, string> = {
  outlook_actionable: "z maila",
  manual_email_reply: "odpowiedzią na maila",
  phone: "telefonicznie",
};

/** Komunikat po odwołaniu — mówi, co naprawdę stało się w Outlooku. */
export const CANCEL_OUTCOME_MESSAGES: Record<CalendarCancelOutcome, string> = {
  cancelled: "Spotkanie odwołane — uczestnicy dostali odwołanie z Outlooka.",
  deleted:
    "Odwołane w NEXUSIE i usunięte z kalendarza Outlook twórcy. Organizatorem jest ktoś inny — uczestnicy nie dostali odwołania.",
  gone: "Odwołane w NEXUSIE — w Outlooku tego spotkania już nie było.",
  skipped:
    "Odwołane tylko w NEXUSIE — twórca nie ma aktywnego połączenia z Microsoft 365, więc Outlook i uczestnicy nie zostali powiadomieni.",
  not_applicable: "Wydarzenie odwołane.",
  already_cancelled: "Wydarzenie było już odwołane.",
};

/** ISO → wartość `<input type="datetime-local">` w czasie lokalnym. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("pl-PL", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export interface EventDetailModalProps {
  event: CalendarEvent;
  onClose: () => void;
  /** Wydarzenie zniknęło (usunięte). */
  onDeleted: () => void;
  /** Wydarzenie się zmieniło (edycja, zakończenie, odwołanie) — nowy stan. */
  onUpdated?: (event: CalendarEvent) => void;
  /** Otwórz formularz feedbacku — okno feedbacku należy do strony. */
  onOpenFeedback?: (eventId: number) => void;
}

export function EventDetailModal({
  event,
  onClose,
  onDeleted,
  onUpdated,
  onOpenFeedback,
}: EventDetailModalProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const cfg = EVENT_TYPE_CONFIG[event.event_type] || EVENT_TYPE_CONFIG.meeting;
  const statusCfg = STATUS_CONFIG[event.status] || STATUS_CONFIG.scheduled;
  const outlook = isOutlookEvent(event);
  const feedbackSources = event.feedback_sources ?? [];

  const invalidateCalendar = () => {
    queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
    queryClient.invalidateQueries({ queryKey: ["calendar-upcoming"] });
    queryClient.invalidateQueries({ queryKey: ["calendar-conflicts-summary"] });
  };

  const deleteMutation = useMutation({
    mutationFn: () => calendarApi.deleteEvent(event.id),
    onSuccess: () => {
      invalidateCalendar();
      onDeleted();
    },
    // Do 09.2026 błąd był niemy: uczestnik cudzego spotkania dostawał 403
    // i okno po prostu nic nie robiło.
    onError: (err: unknown) =>
      toast.showError(apiErrorMessage(err, "Nie udało się usunąć wydarzenia.")),
  });

  const completeMutation = useMutation({
    mutationFn: () => calendarApi.updateEvent(event.id, { status: "completed" }),
    onSuccess: (res) => {
      invalidateCalendar();
      onUpdated?.(res.data as CalendarEvent);
      onClose();
    },
    onError: (err: unknown) =>
      toast.showError(apiErrorMessage(err, "Nie udało się zakończyć wydarzenia.")),
  });

  const cancelMutation = useMutation({
    mutationFn: () => calendarApi.cancelEvent(event.id).then((r) => r.data),
    onSuccess: (data: CalendarCancelResponse) => {
      invalidateCalendar();
      onUpdated?.(data.event as unknown as CalendarEvent);
      const message = CANCEL_OUTCOME_MESSAGES[data.outlook] ?? "Wydarzenie odwołane.";
      if (data.outlook === "skipped") toast.showError(message);
      else toast.showSuccess(message);
    },
    onError: (err: unknown) =>
      toast.showError(apiErrorMessage(err, "Nie udało się odwołać wydarzenia.")),
  });

  const start = new Date(event.start_time);
  const end = event.end_time ? new Date(event.end_time) : null;
  const descriptionText = htmlToPlainText(event.description);
  const joinUrl = event.online_meeting_url ?? event.teams_link ?? null;
  const canCollectFeedback =
    !!event.candidate_id &&
    !!onOpenFeedback &&
    (FEEDBACK_EVENT_TYPES.has(event.event_type) || feedbackSources.length > 0);
  // Odwołać / usunąć może właściciel albo admin (`can_remove` z serwera) —
  // HoR poprawia cudze wydarzenia, ale ich nie odwołuje (decyzja 17.09.2026).
  const canRemove = event.can_remove !== false;
  const canCancel =
    canRemove && event.status !== "cancelled" && (outlook || !!event.candidate_id);
  const canDelete = canRemove && !outlook;
  const deleteMessage =
    feedbackSources.length > 0
      ? `Usunąć „${event.title}”? Zapisany feedback z tej rozmowy zostanie usunięty razem z wydarzeniem.`
      : `Usunąć „${event.title}”?`;

  // Radix `Dialog` (jak każde okno w aplikacji): `role="dialog"`,
  // `aria-modal`, Escape (UAT M03-B11), a od audytu B34 także pułapka fokusu
  // i fokus początkowy — własny `div` przepuszczał Tab do strony pod oknem.
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        size="sm"
        hideClose
        aria-modal="true"
        aria-describedby={undefined}
        className="p-0 gap-0 rounded-2xl"
      >
        <div className={cn("h-1.5 shrink-0 rounded-t-2xl", cfg.dotColor)} />

        {/* Treść przewija się W OKNIE: `DialogContent` ma `max-h-[90dvh]
            overflow-hidden`, więc długi opis z Outlooka ucinał przyciski,
            a Tab do nich przesuwał ukryty kontener i znikał nagłówek. */}
        <div className="p-6 min-h-0 overflow-y-auto" data-testid="calendar-event-detail-body">
          <div className="flex items-start justify-between gap-3 mb-4">
            <div>
              <div className="flex flex-wrap items-center gap-1.5 mb-2">
                <div
                  className={cn(
                    "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold",
                    cfg.bgColor,
                    cfg.color,
                  )}
                >
                  <div className={cn("w-1.5 h-1.5 rounded-full", cfg.dotColor)} />
                  {cfg.label}
                </div>
                {event.needs_attention ? (
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-destructive/15 text-destructive"
                    data-testid="calendar-event-needs-attention"
                  >
                    <AlertTriangle className="w-3 h-3" />
                    Brak feedbacku po rozmowie
                  </span>
                ) : null}
              </div>
              {/* Bez własnego `id`: Radix wiąże `aria-labelledby` okna
                  z WYGENEROWANYM id tytułu, a nadpisanie go odcinało nazwę. */}
              <DialogTitle className="text-lg font-bold text-foreground">
                {event.title}
              </DialogTitle>
            </div>
            <button
              onClick={onClose}
              aria-label="Zamknij"
              className="text-muted-foreground hover:text-muted-foreground shrink-0"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {editing ? (
            <EventEditForm
              event={event}
              onCancel={() => setEditing(false)}
              onSaved={(updated) => {
                invalidateCalendar();
                setEditing(false);
                onUpdated?.(updated);
                toast.showSuccess("Zapisano zmiany w wydarzeniu.");
              }}
            />
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-3 text-sm text-foreground">
                <Clock className="w-4 h-4 text-muted-foreground shrink-0" />
                <span>
                  {event.all_day ? (
                    allDayLabel(event)
                  ) : (
                    <>
                      {start.toLocaleDateString("pl-PL", {
                        weekday: "long",
                        day: "numeric",
                        month: "long",
                      })}{" "}
                      · {start.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}
                      {end &&
                        ` – ${end.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" })}`}
                    </>
                  )}
                </span>
              </div>

              <div className="flex items-center gap-3">
                <CheckCircle className="w-4 h-4 text-muted-foreground" />
                <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", statusCfg.color)}>
                  {statusCfg.label}
                </span>
                {outlook ? (
                  <span className="text-xs text-muted-foreground">z Outlooka</span>
                ) : null}
              </div>

              {event.candidate_name && (
                <div className="flex items-center gap-3 text-sm text-foreground">
                  <User className="w-4 h-4 text-muted-foreground shrink-0" />
                  <span>{event.candidate_name}</span>
                </div>
              )}

              {event.candidate_confirmed_at ? (
                <div className="flex items-center gap-3 text-sm text-foreground">
                  <UserCheck className="w-4 h-4 text-muted-foreground shrink-0" />
                  <span>
                    Kandydat potwierdził {formatDateTime(event.candidate_confirmed_at)}
                    {event.candidate_confirmation_source
                      ? ` (${CONFIRMATION_SOURCE_LABELS[event.candidate_confirmation_source] ?? event.candidate_confirmation_source})`
                      : ""}
                  </span>
                </div>
              ) : null}

              {event.job_title && (
                <div className="flex items-center gap-3 text-sm text-foreground">
                  <Briefcase className="w-4 h-4 text-muted-foreground shrink-0" />
                  <span>{event.job_title}</span>
                </div>
              )}

              {event.location && (
                <div className="flex items-center gap-3 text-sm text-foreground">
                  <MapPin className="w-4 h-4 text-muted-foreground shrink-0" />
                  <span>{event.location}</span>
                </div>
              )}

              {/* Link z Outlooka (`online_meeting_url`) ma pierwszeństwo — do
                  09.2026 okno pokazywało tylko ręczne `teams_link`. */}
              {joinUrl && (
                <div className="flex items-center gap-3 text-sm">
                  <Video className="w-4 h-4 text-muted-foreground shrink-0" />
                  <a
                    href={joinUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline truncate"
                  >
                    Dołącz do spotkania
                  </a>
                </div>
              )}

              <RecordingBlock event={event} />

              {event.attendees && event.attendees.length > 0 && (
                <div className="flex items-start gap-3 text-sm text-foreground">
                  <Users className="w-4 h-4 text-muted-foreground shrink-0 mt-0.5" />
                  <div className="flex flex-wrap gap-1">
                    {/* Uczestnik z M365 to obiekt {address, name} — renderowany wprost
                        wywracał cały kalendarz (React #31). */}
                    {event.attendees.map((attendee, i) => {
                      const label = attendeeLabel(attendee);
                      if (!label) return null;
                      const address = attendeeAddress(attendee);
                      return (
                        <span
                          key={i}
                          title={address && address !== label ? address : undefined}
                          className="px-2 py-0.5 bg-muted text-muted-foreground rounded-full text-xs"
                        >
                          {label}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Wydarzenie z M365 niesie w opisie pełny dokument HTML maila;
                  pokazujemy sam tekst, nigdy `dangerouslySetInnerHTML`. */}
              {descriptionText && (
                <p
                  className="text-sm text-muted-foreground bg-muted rounded-lg p-3 leading-relaxed whitespace-pre-line break-words"
                  data-testid="calendar-event-description"
                >
                  {descriptionText}
                </p>
              )}
            </div>
          )}

          {!editing && (
            <div className="flex flex-wrap gap-2 mt-5 pt-4 border-t border-border">
              {canCollectFeedback && (
                <button
                  type="button"
                  onClick={() => onOpenFeedback?.(event.id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-medium rounded-lg transition-colors"
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  {feedbackSources.length > 0 ? "Edytuj feedback" : "Uzupełnij feedback"}
                </button>
              )}
              {event.status === "scheduled" && (
                <button
                  type="button"
                  onClick={() => completeMutation.mutate()}
                  disabled={completeMutation.isPending}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-lg disabled:opacity-50 transition-colors"
                >
                  <CheckCircle className="w-3.5 h-3.5" />
                  Zakończ
                </button>
              )}
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 border border-border hover:bg-muted text-foreground text-sm font-medium rounded-lg transition-colors"
              >
                <Pencil className="w-3.5 h-3.5" />
                Edytuj
              </button>
              {canCancel && (
                <ConfirmButton
                  onConfirm={() => cancelMutation.mutate()}
                  message={
                    outlook
                      ? `Odwołać „${event.title}” także w Outlooku?`
                      : `Odwołać „${event.title}”?`
                  }
                  confirmLabel="Odwołaj"
                  cancelLabel="Nie"
                  className={`flex items-center gap-1.5 px-3 py-1.5 bg-amber-500/10 border border-amber-500/30 hover:bg-amber-500/20 text-amber-700 dark:text-amber-300 text-sm font-medium rounded-lg transition-colors ${cancelMutation.isPending ? "opacity-50 pointer-events-none" : ""}`}
                >
                  <Ban className="w-3.5 h-3.5" />
                  {cancelMutation.isPending ? "Odwołuję..." : "Odwołaj"}
                </ConfirmButton>
              )}
              {canDelete && (
                <ConfirmButton
                  onConfirm={() => deleteMutation.mutate()}
                  message={deleteMessage}
                  confirmLabel="Usuń"
                  cancelLabel="Anuluj"
                  className={`flex items-center gap-1.5 px-3 py-1.5 bg-destructive/10 border border-destructive/20 hover:bg-destructive/15 text-destructive text-sm font-medium rounded-lg disabled:opacity-50 transition-colors ${deleteMutation.isPending ? "opacity-50 pointer-events-none" : ""}`}
                >
                  <X className="w-3.5 h-3.5" />
                  {deleteMutation.isPending ? "Usuwam..." : "Usuń"}
                </ConfirmButton>
              )}
              <button
                type="button"
                onClick={onClose}
                className="ml-auto px-4 py-1.5 text-sm text-muted-foreground hover:text-foreground"
              >
                Zamknij
              </button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ── Edycja ──────────────────────────────────────────────────────────────────

type EditState = {
  event_type: string;
  candidate: CandidateChoice | null;
  job_id: number | null;
  reminder_minutes: number;
  title: string;
  start_time: string;
  end_time: string;
  location: string;
  description: string;
};

function initialEditState(event: CalendarEvent): EditState {
  return {
    event_type: event.event_type,
    candidate: event.candidate_id
      ? { id: event.candidate_id, label: event.candidate_name || `Kandydat #${event.candidate_id}` }
      : null,
    job_id: event.job_id ?? null,
    reminder_minutes: event.reminder_minutes,
    title: event.title,
    start_time: toLocalInput(event.start_time),
    end_time: toLocalInput(event.end_time),
    location: event.location ?? "",
    description: event.description ?? "",
  };
}

/**
 * Tylko zmienione klucze — PATCH jest częściowy, a odesłanie niezmienionego
 * `job_id` czy terminu wydarzenia z Outlooka budziłoby bramki, które nie mają
 * tu nic do sprawdzenia.
 */
export function changedEventFields(
  event: CalendarEvent,
  form: EditState,
  { outlook }: { outlook: boolean },
): Record<string, unknown> {
  const initial = initialEditState(event);
  const out: Record<string, unknown> = {};
  if (form.event_type !== initial.event_type) out.event_type = form.event_type;
  if ((form.candidate?.id ?? null) !== (initial.candidate?.id ?? null)) {
    out.candidate_id = form.candidate?.id ?? null;
  }
  if (form.job_id !== initial.job_id) out.job_id = form.job_id;
  if (form.reminder_minutes !== initial.reminder_minutes) {
    out.reminder_minutes = form.reminder_minutes;
  }
  // 0338: termin, tytuł, miejsce i opis wydarzenia z Outlooka idą do Outlooka
  // organizatora (serwer przepycha je PATCH-em przed zapisem lokalnym).
  // Całodniowe z Outlooka dalej edytujemy wyłącznie w Outlooku.
  if (event.all_day) {
    if (!outlook && form.title.trim() !== initial.title) out.title = form.title.trim();
    if (!outlook && form.location !== initial.location) out.location = form.location || null;
    if (!outlook && form.description !== initial.description) {
      out.description = form.description || null;
    }
    return out;
  }
  if (form.title.trim() !== initial.title) out.title = form.title.trim();
  if (form.start_time !== initial.start_time && form.start_time) {
    out.start_time = new Date(form.start_time).toISOString();
  }
  if (form.end_time !== initial.end_time) {
    out.end_time = form.end_time ? new Date(form.end_time).toISOString() : null;
  }
  if (form.location !== initial.location) out.location = form.location || null;
  if (form.description !== initial.description) out.description = form.description || null;
  return out;
}

const INPUT =
  "w-full border border-border rounded-lg px-3 py-2 text-sm bg-card focus:outline-hidden focus:ring-2 focus-visible:ring-ring";

function EventEditForm({
  event,
  onCancel,
  onSaved,
}: {
  event: CalendarEvent;
  onCancel: () => void;
  onSaved: (event: CalendarEvent) => void;
}) {
  const outlook = isOutlookEvent(event);
  const [form, setForm] = useState<EditState>(() => initialEditState(event));
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (data: Record<string, unknown>) => calendarApi.updateEvent(event.id, data),
    onSuccess: (res) => onSaved(res.data as CalendarEvent),
    onError: (err: unknown) => setError(apiErrorMessage(err, "Nie udało się zapisać zmian.")),
  });

  const submit = () => {
    setError(null);
    if (!(outlook && event.all_day) && !form.title.trim()) {
      setError("Tytuł jest wymagany.");
      return;
    }
    if (!event.all_day) {
      if (!form.start_time) {
        setError("Czas rozpoczęcia jest wymagany.");
        return;
      }
      if (form.end_time && new Date(form.end_time) <= new Date(form.start_time)) {
        setError("Koniec wydarzenia musi być późniejszy niż jego początek.");
        return;
      }
    }
    const changes = changedEventFields(event, form, { outlook });
    if (Object.keys(changes).length === 0) {
      onCancel();
      return;
    }
    mutation.mutate(changes);
  };

  return (
    <div className="space-y-3" data-testid="calendar-event-edit-form">
      {outlook ? (
        <p className="text-xs text-muted-foreground bg-muted rounded-lg px-3 py-2">
          {event.all_day
            ? "To wydarzenie pochodzi z Outlooka — termin, tytuł, miejsce i uczestników zmieniasz w Outlooku. Tutaj ustawisz typ, kandydata, rekrutację i przypomnienie."
            : "To wydarzenie pochodzi z Outlooka — zmiana terminu, tytułu, miejsca lub opisu trafi też do Outlooka i do uczestników. Uczestników zmieniasz w Outlooku."}
        </p>
      ) : null}

      {!(outlook && event.all_day) && (
        <div>
          <label htmlFor="event-edit-title" className="text-xs font-semibold text-muted-foreground block mb-1">
            Tytuł
          </label>
          <input
            id="event-edit-title"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            className={INPUT}
          />
        </div>
      )}

      <div>
        <label htmlFor="event-edit-type" className="text-xs font-semibold text-muted-foreground block mb-1">
          Typ
        </label>
        <select
          id="event-edit-type"
          value={form.event_type}
          onChange={(e) => setForm({ ...form, event_type: e.target.value })}
          className={INPUT}
        >
          {Object.entries(EVENT_TYPE_CONFIG).map(([key, c]) => (
            <option key={key} value={key}>
              {c.label}
            </option>
          ))}
        </select>
      </div>

      {!event.all_day && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label htmlFor="event-edit-start" className="text-xs font-semibold text-muted-foreground block mb-1">
              Od
            </label>
            <input
              id="event-edit-start"
              type="datetime-local"
              value={form.start_time}
              onChange={(e) => setForm({ ...form, start_time: e.target.value })}
              className={INPUT}
            />
          </div>
          <div>
            <label htmlFor="event-edit-end" className="text-xs font-semibold text-muted-foreground block mb-1">
              Do
            </label>
            <input
              id="event-edit-end"
              type="datetime-local"
              value={form.end_time}
              onChange={(e) => setForm({ ...form, end_time: e.target.value })}
              className={INPUT}
            />
          </div>
        </div>
      )}

      <div>
        <label id="event-edit-candidate-label" className="text-xs font-semibold text-muted-foreground block mb-1">
          Kandydat
        </label>
        <CandidateCombobox
          labelledBy="event-edit-candidate-label"
          value={form.candidate}
          onChange={(candidate) =>
            setForm({
              ...form,
              candidate,
              // Rekrutacja należy do kandydata — zmiana osoby ją zeruje.
              job_id: candidate?.id === form.candidate?.id ? form.job_id : null,
            })
          }
        />
      </div>

      <div>
        <label htmlFor="event-edit-job" className="text-xs font-semibold text-muted-foreground block mb-1">
          Rekrutacja
        </label>
        <RecruitmentSelect
          id="event-edit-job"
          candidateId={form.candidate?.id ?? null}
          value={form.job_id}
          currentLabel={form.job_id === event.job_id ? event.job_title : null}
          autoSelectSingle={form.candidate?.id !== event.candidate_id}
          onChange={(job_id) => setForm((f) => ({ ...f, job_id }))}
        />
      </div>

      {!(outlook && event.all_day) && (
        <div>
          <label htmlFor="event-edit-location" className="text-xs font-semibold text-muted-foreground block mb-1">
            Lokalizacja
          </label>
          <input
            id="event-edit-location"
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            className={INPUT}
          />
        </div>
      )}

      <div>
        <label htmlFor="event-edit-reminder" className="text-xs font-semibold text-muted-foreground block mb-1">
          Przypomnienie
        </label>
        <select
          id="event-edit-reminder"
          value={form.reminder_minutes}
          onChange={(e) => setForm({ ...form, reminder_minutes: Number(e.target.value) })}
          className={INPUT}
        >
          {/* Wartość spoza listy (np. 0 z integracji) nie może zniknąć z pola. */}
          {!REMINDER_OPTIONS.some((o) => o.value === form.reminder_minutes) ? (
            <option value={form.reminder_minutes}>{form.reminder_minutes} min przed</option>
          ) : null}
          {REMINDER_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {!(outlook && event.all_day) && (
        <div>
          <label htmlFor="event-edit-description" className="text-xs font-semibold text-muted-foreground block mb-1">
            Opis
          </label>
          <textarea
            id="event-edit-description"
            rows={2}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            className={cn(INPUT, "resize-none")}
          />
        </div>
      )}

      {error ? (
        <div role="alert" className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
          {error}
        </div>
      ) : null}

      <div className="flex justify-end gap-2 pt-2 border-t border-border">
        <button
          type="button"
          onClick={onCancel}
          className="px-4 py-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          Anuluj
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={mutation.isPending}
          className="px-4 py-1.5 bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-semibold rounded-lg disabled:opacity-50"
        >
          {mutation.isPending ? "Zapisuję…" : "Zapisz zmiany"}
        </button>
      </div>
    </div>
  );
}
