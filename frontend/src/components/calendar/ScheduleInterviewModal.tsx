"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, Loader2 } from "lucide-react";

import { microsoft365Api } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

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
  const [error, setError] = useState<string | null>(null);

  const end = useMemo(() => {
    try {
      const s = new Date(start);
      s.setMinutes(s.getMinutes() + duration);
      return s.toISOString();
    } catch {
      return start;
    }
  }, [start, duration]);

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
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["candidate-calls", candidateId] });
      queryClient.invalidateQueries({ queryKey: ["calendar-events"] });
      onOpenChange(false);
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

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Zaplanuj spotkanie z kandydatem</DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Tytuł
            </label>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">
                Typ
              </label>
              <select
                value={eventType}
                onChange={(e) => setEventType(e.target.value as EventType)}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm bg-white"
              >
                {Object.entries(EVENT_TYPE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">
                Długość
              </label>
              <select
                value={duration}
                onChange={(e) => setDuration(parseInt(e.target.value, 10))}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm bg-white"
              >
                <option value={30}>30 min</option>
                <option value={45}>45 min</option>
                <option value={60}>60 min</option>
                <option value={90}>90 min</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Początek (czas lokalny)
            </label>
            <Input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">
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
            <label className="block text-xs font-medium text-gray-500 mb-1">
              Dodatkowi uczestnicy (e-maile, rozdziel przecinkami)
            </label>
            <Input
              value={extraAttendees}
              onChange={(e) => setExtraAttendees(e.target.value)}
              placeholder="client@firma.com, kolega@b2bnet.pl"
            />
          </div>

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={inviteCandidate}
              onChange={(e) => setInviteCandidate(e.target.checked)}
              disabled={!candidateEmail}
            />
            Zaproś kandydata{" "}
            {candidateEmail ? (
              <span className="text-gray-400">({candidateEmail})</span>
            ) : (
              <span className="text-red-500">(brak adresu email)</span>
            )}
          </label>

          {error && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
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
            className="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-800 disabled:opacity-50"
          >
            Anuluj
          </button>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
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
