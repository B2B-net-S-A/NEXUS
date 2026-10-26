/**
 * Tematy ikon górnego paska zamiast dzwonka (16.10.2026).
 *
 * Temat liczy backend (`backend/app/services/notification_topics.py`) i dokłada
 * go do ramki gniazda (`topic`, `toast`); front go nie zgaduje. Reguła:
 * `docs/claude/powiadomienia/pasek-tematy-bez-dzwonka.md`.
 */

export type NotificationTopic =
  | "messages"
  | "interviews"
  | "cv"
  | "my_people"
  | "jobs"
  | "contracts"
  | "other";

/**
 * Ramka `notification` z gniazda, którą `NotificationsRealtime` rozgłasza
 * dalej (poza rozmowami i notatkami — te mają własne okienka).
 */
export const NOTIFICATION_FRAME_EVENT = "nexus:notification-frame";

/** Wzmianka i odpowiedź w notatce należą do okienka „Wiadomości”. */
export const NOTE_NOTIFICATION_TYPES = ["note_mention", "note_reply"] as const;
export type NoteNotificationType = (typeof NOTE_NOTIFICATION_TYPES)[number];

export function isNoteNotificationType(
  type: string | null | undefined,
): type is NoteNotificationType {
  return (NOTE_NOTIFICATION_TYPES as readonly string[]).includes(type ?? "");
}

/** „Moi ludzie” bez wiersza powiadomienia — samo zdarzenie na żywo. */
export const MY_PEOPLE_MATCH_FRAME = "my_people:match";

/** Ustawienia „Moje powiadomienia” (Ustawienia → Moje konto). */
export const MY_NOTIFICATIONS_SETTINGS_HREF = "/settings?item=my-notifications";
