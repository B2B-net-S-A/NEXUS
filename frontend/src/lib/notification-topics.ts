/**
 * Tematy ikon górnego paska zamiast dzwonka (16.10.2026).
 *
 * Temat liczy backend (`backend/app/services/notification_topics.py`) i dokłada
 * go do ramki gniazda (`topic`, `toast`); front go nie zgaduje. Reguła:
 * `docs/claude/powiadomienia/pasek-tematy-bez-dzwonka.md`.
 */

import type { QueryClient } from "@tanstack/react-query";

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

/**
 * Ostatni człon klucza listy okienka tematu — `["notifications", scope, "chats"]`
 * itd. (`lib/api/chatNotifications.ts`, `interviewNotifications.ts`,
 * `jobTopic.ts`, `contractTopic.ts`).
 */
const TOPIC_LIST_LEAF: Partial<Record<NotificationTopic, string>> = {
  messages: "chats",
  interviews: "interviews",
  jobs: "jobs",
  contracts: "contracts",
};
const TOPIC_LIST_LEAVES: ReadonlySet<string> = new Set(Object.values(TOPIC_LIST_LEAF));

/**
 * Odśwież listy powiadomień po zdarzeniu z gniazda (27.10.2026).
 *
 * Do tej daty każda ramka unieważniała cały prefiks `["notifications"]`, czyli
 * cztery okienka paska naraz (~920 żądań na godzinę każde na prod). Teraz
 * ramka odświeża listę SWOJEGO tematu i listy spoza okienek (pulpit), a temat
 * bez okienka (`cv`, `my_people`, `other`) — tylko te drugie. Ramka bez tematu
 * (backend sprzed 16.10.2026) albo `null` (powrót gniazda, odpytywanie bez
 * gniazda) odświeża wszystko, jak dawniej.
 */
export function invalidateNotificationLists(
  queryClient: QueryClient,
  topic: string | null | undefined,
): void {
  if (!topic) {
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
    return;
  }
  const own = TOPIC_LIST_LEAF[topic as NotificationTopic];
  queryClient.invalidateQueries({
    queryKey: ["notifications"],
    predicate: (query) => {
      const leaf = query.queryKey[2];
      return typeof leaf !== "string" || !TOPIC_LIST_LEAVES.has(leaf) || leaf === own;
    },
  });
}
