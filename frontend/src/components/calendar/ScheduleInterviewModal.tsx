"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Check, Copy, Loader2 } from "lucide-react";

import {
  calendarApi,
  microsoft365Api,
  type CalendarEventResponse,
  type FreeBusyResponse,
} from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Alert } from "@/components/ui/alert";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useAuthStore } from "@/store/auth";

interface ConflictItem {
  id: number;
  title: string;
  event_type: string;
  status: string;
  start_time: string;
  end_time: string | null;
  candidate_id: number | null;
  candidate_name: string | null;
}

interface ConflictsResponse {
  user_id: number;
  start: string;
  end: string;
  conflicts: ConflictItem[];
}

function formatConflictTime(start: string, end: string | null): string {
  const s = new Date(start);
  const fmt = new Intl.DateTimeFormat("pl-PL", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  if (!end) return fmt.format(s);
  const e = new Date(end);
  const time = new Intl.DateTimeFormat("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${fmt.format(s)}–${time.format(e)}`;
}

interface ScheduleInterviewModalProps {
  candidateId: number;
  candidateName: string;
  candidateEmail: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type EventType = "interview" | "screening" | "prep_call" | "meeting";

const EVENT_TYPE_LABELS: Record<EventType, string> = {
  interview: "Interview",
  screening: "Screening",
  prep_call: "Prep call",
  meeting: "Spotkanie",
};

// Event types that default to including a Teams meeting link. Mirrors
// `_TEAMS_DEFAULT_EVENT_TYPES` in backend/app/services/m365/calendar.py — keep
// in sync so the checkbox default matches what the server would pick.
const TEAMS_DEFAULT_FOR: ReadonlySet<EventType> = new Set<EventType>([
  "interview",
  "screening",
]);

export default function ScheduleInterviewModal({
  candidateId,
  candidateName,
  candidateEmail,
  open,
  onOpenChange,
}: ScheduleInterviewModalProps) {
  const queryClient = useQueryClient();
  const defaultStart = useMemo(() => nextHourIso(), []);

  const [title, setTitle] = useState(`Interview: ${candidateName}`);
  const [description, setDescription] = useState("");
  const [eventType, setEventType] = useState<EventType>("interview");
  const [start, setStart] = useState(defaultStart);
  const [duration, setDuration] = useState(45); // minutes
  const [inviteCandidate, setInviteCandidate] = useState(true);
  const [extraAttendees, setExtraAttendees] = useState("");
  // Phase 7.1 — opt-in Teams meeting link. `userTouched` records whether the
  // user toggled the checkbox manually; until then, switching event_type
  // adjusts the default automatically.
  const [addTeamsMeeting, setAddTeamsMeeting] = useState(true);
  const [teamsTouched, setTeamsTouched] = useState(false);
  const [createdEvent, setCreatedEvent] =
    useState<CalendarEventResponse | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!teamsTouched) {
      setAddTeamsMeeting(TEAMS_DEFAULT_FOR.has(eventType));
    }
  }, [eventType, teamsTouched]);

  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(t);
  }, [copied]);

  const end = useMemo(() => {
    try {
      const s = new Date(start);
      s.setMinutes(s.getMinutes() + duration);
      return s.toISOString();
    } catch {
      return start;
    }
  }, [start, duration]);

  // Free-busy advisory: ask Graph whether the recruiter (and candidate, if we
  // have their email) is already booked in the chosen window. Debounced so we
  // don't fire a Graph call on every keystroke. Errors and "unknown" statuses
  // intentionally render nothing — the API does not affect submit.
  const currentUserEmail = useAuthStore((s) => s.user?.email ?? null);
  const debouncedStart = useDebouncedValue(start, 500);
  const debouncedDuration = useDebouncedValue(duration, 500);
  const checkAttendees = useMemo(() => {
    const out: string[] = [];
    if (currentUserEmail) out.push(currentUserEmail);
    if (inviteCandidate && candidateEmail) out.push(candidateEmail);
    return out;
  }, [currentUserEmail, inviteCandidate, candidateEmail]);
  const checkWindow = useMemo(() => {
    try {
      const s = new Date(debouncedStart);
      if (Number.isNaN(s.getTime())) return null;
      const e = new Date(s);
      e.setMinutes(e.getMinutes() + debouncedDuration);
      return { start: s.toISOString(), end: e.toISOString() };
    } catch {
      return null;
    }
  }, [debouncedStart, debouncedDuration]);

  const freeBusy = useQuery<FreeBusyResponse>({
    queryKey: [
      "m365-free-busy",
      checkWindow?.start,
      checkWindow?.end,
      checkAttendees.join(","),
    ],
    queryFn: async () => {
      const res = await microsoft365Api.checkFreeBusy({
        start: checkWindow!.start,
        end: checkWindow!.end,
        attendees: checkAttendees,
      });
      return res.data;
    },
    enabled: open && checkWindow !== null && checkAttendees.length > 0,
    // M365 connection missing / Graph upstream blip — surface nothing rather
    // than spam the modal with retry banners. Submit is still allowed.
    retry: false,
    staleTime: 30_000,
  });

  const conflictHint = useMemo(() => {
    if (!freeBusy.data || !checkWindow) return null;
    const blockingStatuses = new Set(["busy", "oof"]);
    const recruiterSlots = currentUserEmail
      ? freeBusy.data.attendees[currentUserEmail] ?? []
      : [];
    const recruiterConflict = recruiterSlots.some((s) =>
      blockingStatuses.has(s.status),
    );
    const candidateSlots =
      inviteCandidate && candidateEmail
        ? freeBusy.data.attendees[candidateEmail] ?? []
        : [];
    const candidateConflict = candidateSlots.some((s) =>
      blockingStatuses.has(s.status),
    );
    if (recruiterConflict) {
      return {
        variant: "error" as const,
        title: "Konflikt w Twoim kalendarzu",
        description:
          "Masz już zajęty termin w tym oknie. Możesz nadal kontynuować, ale sprawdź Outlook.",
      };
    }
    if (candidateConflict) {
      return {
        variant: "warning" as const,
        title: "Kandydat może mieć inne spotkanie",
        description:
          "Outlook kandydata pokazuje zajętość w wybranym terminie.",
      };
    }
    // Both sides free — only celebrate when we actually checked both.
    if (currentUserEmail && (!inviteCandidate || candidateEmail)) {
      return {
        variant: "success" as const,
        title: "Oba terminy wolne",
        description: undefined,
      };
    }
    return null;
  }, [
    freeBusy.data,
    checkWindow,
    currentUserEmail,
    candidateEmail,
    inviteCandidate,
  ]);

  // Phase 5.4 — Nexus-side overlap check against the recruiter's own calendar
  // events (interviews/screenings already booked here, not in Outlook). Reuses
  // the same debounced inputs so we share one keystroke window with free-busy.
  const conflictsQuery = useQuery<ConflictsResponse>({
    queryKey: ["calendar-conflicts", checkWindow?.start, checkWindow?.end],
    enabled: open && checkWindow !== null,
    queryFn: async () => {
      const res = await calendarApi.conflicts({
        start: checkWindow!.start,
        end: checkWindow!.end,
      });
      return res.data as ConflictsResponse;
    },
  });
  const conflicts = conflictsQuery.data?.conflicts ?? [];

  const mutation = useMutation({
    mutationFn: () =>
      microsoft365Api.createInvite({
        candidate_id: candidateId,
        title,
        description,
        start: new Date(start).toISOString(),
        end,
        event_type: eventType,
        extra_attendees: extraAttendees
          .split(/[,;]/)
          .map((s) => s.trim())
          .filter(Boolean),
        invite_candidate: inviteCandidate,
        add_teams_meeting: addTeamsMeeting,
      }),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["candidate-calls", candidateId] });
      queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
      // Linger on a confirmation step when Graph returned a Teams join URL —
      // recruiter wants to copy it into the candidate ping. When no URL is
      // present (non-Teams event or older backend) we close immediately.
      if (res.data?.online_meeting_url) {
        setCreatedEvent(res.data);
      } else {
        onOpenChange(false);
      }
    },
    onError: (err: unknown) => {
      const msg =
        typeof err === "object" && err !== null && "response" in err
          ? (
              (err as { response?: { data?: { detail?: string } } }).response?.data
                ?.detail ?? "Nie udało się zapisać spotkania."
            )
          : "Nie udało się zapisać spotkania.";
      setError(msg);
    },
  });

  const handleCopyMeetingUrl = async () => {
    const url = createdEvent?.online_meeting_url;
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      // Clipboard API may be unavailable on http: origins or in some browsers.
      // The link remains visible/selectable, so silent failure is acceptable.
    }
  };

  const handleClose = () => {
    setCreatedEvent(null);
    setCopied(false);
    onOpenChange(false);
  };

  if (createdEvent) {
    return (
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Spotkanie zaplanowane</DialogTitle>
          </DialogHeader>
          <div className="flex-1 min-h-0 space-y-3 px-6 py-4 overflow-y-auto">
            <Alert
              variant="success"
              title="Link Teams wygenerowany"
              description="Outlook wysłał zaproszenie do uczestników. Link można skopiować poniżej."
            />
            {createdEvent.online_meeting_url && (
              <div className="space-y-2">
                <label className="block text-xs font-medium text-muted-foreground">
                  Link do spotkania
                </label>
                <div className="flex items-center gap-2">
                  <a
                    href={createdEvent.online_meeting_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-1 min-w-0 truncate text-sm text-primary underline"
                  >
                    {createdEvent.online_meeting_url}
                  </a>
                  <button
                    type="button"
                    onClick={handleCopyMeetingUrl}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-border rounded-lg hover:bg-muted"
                  >
                    {copied ? (
                      <>
                        <Check className="h-3.5 w-3.5" />
                        Skopiowano
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5" />
                        Kopiuj link Teams
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
          <DialogFooter>
            <button
              onClick={handleClose}
              className="px-4 py-2 bg-primary hover:bg-primary/90 text-white rounded-lg text-sm font-medium"
            >
              Zamknij
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Zaplanuj spotkanie z kandydatem</DialogTitle>
        </DialogHeader>

        <div className="flex-1 min-h-0 space-y-3 px-6 py-4 overflow-y-auto">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Tytuł
            </label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">
                Typ
              </label>
              <select
                value={eventType}
                onChange={(e) => setEventType(e.target.value as EventType)}
                className="w-full rounded-lg border border-border px-3 py-2 text-sm bg-card"
              >
                {Object.entries(EVENT_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">
                Długość
              </label>
              <select
                value={duration}
                onChange={(e) => setDuration(parseInt(e.target.value, 10))}
                className="w-full rounded-lg border border-border px-3 py-2 text-sm bg-card"
              >
                <option value={30}>30 min</option>
                <option value={45}>45 min</option>
                <option value={60}>60 min</option>
                <option value={90}>90 min</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Początek (czas lokalny)
            </label>
            <Input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
            {conflictHint && (
              <div className="mt-2">
                <Alert
                  variant={conflictHint.variant}
                  title={conflictHint.title}
                  description={conflictHint.description}
                />
              </div>
            )}
          </div>

          {conflicts.length > 0 && (
            <Alert
              variant="warning"
              title={
                conflicts.length === 1
                  ? "Masz inny event w tym oknie"
                  : `Masz ${conflicts.length} inne eventy w tym oknie`
              }
            >
              <ul className="mt-1 space-y-0.5 text-xs">
                {conflicts.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-baseline gap-x-2">
                    <span className="font-medium">{c.title}</span>
                    <span className="opacity-80">
                      {formatConflictTime(c.start_time, c.end_time)}
                    </span>
                    {c.candidate_name && (
                      <span className="opacity-70">— {c.candidate_name}</span>
                    )}
                  </li>
                ))}
              </ul>
            </Alert>
          )}

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Opis / Agenda (opcjonalnie)
            </label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Punkty do omówienia, link do CV, itd."
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Dodatkowi uczestnicy (e-maile, rozdziel przecinkami)
            </label>
            <Input
              value={extraAttendees}
              onChange={(e) => setExtraAttendees(e.target.value)}
              placeholder="client@firma.com, kolega@b2bnet.pl"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={inviteCandidate}
              onChange={(e) => setInviteCandidate(e.target.checked)}
              disabled={!candidateEmail}
            />
            Zaproś kandydata{" "}
            {candidateEmail ? (
              <span className="text-muted-foreground">({candidateEmail})</span>
            ) : (
              <span className="text-destructive">(brak adresu email)</span>
            )}
          </label>

          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={addTeamsMeeting}
              onChange={(e) => {
                setTeamsTouched(true);
                setAddTeamsMeeting(e.target.checked);
              }}
            />
            Dodaj spotkanie Teams
            <span className="text-muted-foreground text-xs">
              (link wygenerowany przez Outlook)
            </span>
          </label>

          {error && (
            <div className="text-sm text-destructive bg-destructive/10 border border-destructive/20 rounded-lg px-3 py-2">
              {error}
              {error.includes("Microsoft 365") && (
                <a href="/settings" className="ml-2 underline">
                  Przejdź do ustawień
                </a>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <button
            onClick={() => onOpenChange(false)}
            disabled={mutation.isPending}
            className="px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            Anuluj
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Tworzę...
              </>
            ) : (
              <>
                <CalendarPlus className="h-4 w-4" />
                Zaplanuj w Outlook
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function nextHourIso(): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  // <input type="datetime-local"> requires YYYY-MM-DDTHH:mm (local, no TZ).
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
