// Powiadomienia kategorii „Rozmowy” — rozmowy u klienta, prepy, terminy,
// telefon po rozmowie i przypomnienia kalendarza. Od 13.10.2026 mają własne
// okienko w górnym pasku (`InterviewNotificationsDropdown`), tak jak czaty.

import { parseCycleParam } from "@/lib/interview-cycle";

/**
 * Lustro `types_in(NotificationCategory.interviews)` z backendu (pilnuje
 * `interview-notifications.test.ts`). Ładunek gniazda nie niesie kategorii,
 * więc front rozpoznaje te powiadomienia po typie.
 */
export const INTERVIEW_NOTIFICATION_TYPES = [
  "interview_scheduled",
  "post_interview_t15",
  "post_interview_t45",
  "post_interview_t2h_escalation",
  "interview_slots_requested",
  "interview_slot_chosen",
  "interview_slot_confirmed",
  "interview_debrief_saved",
  "prep_attention",
] as const;

export type InterviewNotificationType = (typeof INTERVIEW_NOTIFICATION_TYPES)[number];

const TYPE_SET: ReadonlySet<string> = new Set(INTERVIEW_NOTIFICATION_TYPES);

export function isInterviewNotificationType(
  type: string | null | undefined,
): type is InterviewNotificationType {
  return type != null && TYPE_SET.has(type);
}

/** Zdarzenie okna: gniazdo dostarczyło powiadomienie kategorii „Rozmowy”. */
export const INTERVIEW_NOTIFY_EVENT = "nexus:interview-notify";

/** Zdarzenie okna: otwórz okienko „Rozmowy” (podpowiedź w dzwonku). */
export const OPEN_INTERVIEWS_WINDOW_EVENT = "nexus:open-interviews-window";

export interface InterviewLinkTarget {
  /** Para z `?cycle=<kandydat>-<rekrutacja>`. */
  pair: { candidateId: number; jobId: number } | null;
  /** Wydarzenie z `&debrief=` albo `?event=`. */
  eventId: number | null;
}

/**
 * Do czego prowadzi link powiadomienia: `/calendar?cycle=12-34`,
 * `/calendar?cycle=12-34&debrief=7`, `/calendar?event=7` albo
 * `/calendar?event=7&action=feedback`. Parametry czytamy po nazwie —
 * dopasowanie po początku tekstu złapałoby `cycle=12-345` jako parę 12-34.
 */
export function parseInterviewLink(link: string | null | undefined): InterviewLinkTarget {
  const mark = link ? link.indexOf("?") : -1;
  if (!link || mark < 0) return { pair: null, eventId: null };
  const params = new URLSearchParams(link.slice(mark + 1));
  const id = Number(params.get("debrief") ?? params.get("event"));
  return {
    pair: parseCycleParam(params.get("cycle")),
    eventId: Number.isSafeInteger(id) && id > 0 ? id : null,
  };
}
