"use client";

/**
 * Wspólne definicje kalendarza: konfiguracja typów/statusów, kształt
 * wydarzenia w widoku i blok nagrania. Wyniesione z `app/calendar/page.tsx`,
 * kiedy okno wydarzenia stało się osobnym komponentem.
 */

import { Loader2, PlayCircle } from "lucide-react";

import type { CalendarAttendee } from "@/lib/calendar-attendees";

export const EVENT_TYPE_CONFIG: Record<
  string,
  { label: string; color: string; bgColor: string; borderColor: string; dotColor: string }
> = {
  interview: {
    label: "Rozmowa kwalifikacyjna",
    color: "text-primary",
    bgColor: "bg-primary/15",
    borderColor: "border-primary/30",
    dotColor: "bg-primary",
  },
  screening: {
    label: "Screening",
    color: "text-green-700",
    bgColor: "bg-green-100",
    borderColor: "border-green-300",
    dotColor: "bg-green-500",
  },
  prep_call: {
    label: "Prep Call",
    color: "text-purple-700",
    bgColor: "bg-purple-100",
    borderColor: "border-purple-300",
    dotColor: "bg-purple-500",
  },
  meeting: {
    label: "Spotkanie",
    color: "text-foreground",
    bgColor: "bg-muted",
    borderColor: "border-border",
    dotColor: "bg-gray-400",
  },
  deadline: {
    label: "Deadline",
    color: "text-destructive",
    bgColor: "bg-destructive/15",
    borderColor: "border-red-300",
    dotColor: "bg-destructive",
  },
};

export const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  scheduled: { label: "Zaplanowane", color: "bg-primary/15 text-primary" },
  completed: { label: "Zakończone", color: "bg-green-100 text-green-700" },
  cancelled: { label: "Odwołane", color: "bg-destructive/15 text-destructive" },
};

export const HOURS = Array.from({ length: 13 }, (_, i) => i + 8); // 8:00 – 20:00

export const DAY_NAMES = ["Pon", "Wt", "Śr", "Czw", "Pt", "Sob", "Nd"];
export const DAY_NAMES_FULL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"];

export type CalendarEvent = {
  id: number;
  title: string;
  description?: string;
  event_type: string;
  start_time: string;
  end_time?: string;
  all_day: boolean;
  candidate_id?: number;
  candidate_name?: string;
  job_id?: number;
  job_title?: string;
  client_id?: number;
  client_name?: string;
  attendees?: CalendarAttendee[];
  location?: string;
  teams_link?: string;
  // Phase 7.1 — Graph-generated Teams meeting join URL (distinct from the
  // legacy free-text `teams_link`).
  online_meeting_url?: string | null;
  // Phase 7.8 — OneDrive share link to the published Teams recording.
  recording_url?: string | null;
  reminder_minutes: number;
  status: string;
  created_at?: string;
  created_by?: number | null;
  /** Eskalacja T+2h: rozmowa bez feedbacku. */
  needs_attention?: boolean;
  candidate_confirmed_at?: string | null;
  candidate_confirmation_source?: string | null;
  /** `microsoft365` — wydarzenie żyje w Outlooku (odwołuje się, nie usuwa). */
  external_source?: string | null;
  /** Strony feedbacku zapisane pod wydarzeniem. */
  feedback_sources?: string[];
  /** Czy wołający może odwołać / usunąć (właściciel albo admin). */
  can_remove?: boolean;
};

export const OUTLOOK_SOURCE = "microsoft365";

export function isOutlookEvent(ev: Pick<CalendarEvent, "external_source">): boolean {
  return ev.external_source === OUTLOOK_SOURCE;
}

/** Typy, po których zbieramy feedback (reszta to spotkania wewnętrzne). */
export const FEEDBACK_EVENT_TYPES: ReadonlySet<string> = new Set(["interview", "screening"]);

export const REMINDER_OPTIONS: ReadonlyArray<{ value: number; label: string }> = [
  { value: 5, label: "5 minut przed" },
  { value: 10, label: "10 minut przed" },
  { value: 15, label: "15 minut przed" },
  { value: 30, label: "30 minut przed" },
  { value: 60, label: "1 godzina przed" },
];

// ── Teams meeting recording block (Phase 7.8) ───────────────────────────────
//
// Renders one of three states under the event details panel:
//   1. `recording_url` set → "Odsłuchaj nagranie" link (opens OneDrive).
//   2. `online_meeting_url` set + event ended >1h ago → searching hint.
//   3. Otherwise → render nothing (no Teams meeting or too recent to nag).
//
// The discovery loop runs every 6h, so we tell users explicitly the search
// is still ongoing instead of letting them assume the recording will never
// arrive when it just hasn't been scanned yet.

interface RecordingBlockProps {
  event: CalendarEvent;
}

export function RecordingBlock({ event }: RecordingBlockProps) {
  if (event.recording_url) {
    return (
      <div className="flex items-center gap-3 text-sm rounded-md border border-violet-500/30 bg-violet-500/5 px-3 py-2">
        <PlayCircle className="w-4 h-4 text-violet-600 shrink-0" />
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-xs font-medium text-violet-700 dark:text-violet-300">
            Nagranie z interview
          </span>
          <a
            href={event.recording_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline truncate text-sm"
          >
            Odsłuchaj nagranie
          </a>
        </div>
      </div>
    );
  }

  // Hint state — meeting happened, no recording yet but the discovery loop
  // is still scanning OneDrive. Only nag once the event ended at least 1h
  // ago (Teams typically publishes within an hour).
  if (!event.online_meeting_url || !event.end_time) {
    return null;
  }
  const endedAt = new Date(event.end_time);
  const ONE_HOUR_MS = 60 * 60 * 1000;
  if (endedAt.getTime() > Date.now() - ONE_HOUR_MS) {
    return null;
  }

  return (
    <div className="flex items-start gap-3 text-xs text-muted-foreground rounded-md border border-muted bg-muted/30 px-3 py-2">
      <Loader2 className="w-3.5 h-3.5 shrink-0 mt-0.5 animate-spin opacity-60" />
      <span>
        Nagranie nie zostało jeszcze znalezione. Sprawdź folder Recordings na
        OneDrive organizatora.
      </span>
    </div>
  );
}

