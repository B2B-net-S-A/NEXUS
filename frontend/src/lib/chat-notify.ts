import type { ChatNotifyEvent } from "@/types/job-chat";

/** Tyle czeka kolejny dymek o zwykłej wiadomości z tej samej rozmowy. */
export const CHAT_TOAST_QUIET_MS = 20_000;

export function chatThreadKey(kind: string, entityId: number): string {
  return `${kind}:${entityId}`;
}

/** Zdanie w dymku o nowej wiadomości czatu. */
export function chatNotifyMessage(event: ChatNotifyEvent): string {
  if (event.kind === "note") {
    // Tytuł powiadomienia mówi już kto i co („Anna D. oznaczył(a) Cię w notatce”).
    const preview = event.preview.trim();
    return preview ? `${event.thread_title}: ${preview}` : event.thread_title;
  }
  const where =
    event.kind === "candidate"
      ? `w czacie kandydata „${event.thread_title}”`
      : `w czacie „${event.thread_title}”`;
  const lead =
    event.notification_type === "job_chat_mention"
      ? `${event.author_name} oznaczył(a) Cię ${where}`
      : `${event.author_name} ${where}`;
  const preview = event.preview.trim();
  return preview ? `${lead}: ${preview}` : lead;
}

/**
 * Czy pokazać dymek: wzmianka zawsze, zwykła wiadomość najwyżej raz na
 * `CHAT_TOAST_QUIET_MS` w rozmowie — żywa rozmowa nie zasypuje ekranu.
 * `lastShown` jest aktualizowane w miejscu.
 */
export function shouldShowChatToast(
  event: ChatNotifyEvent,
  lastShown: Map<string, number>,
  now: number,
): boolean {
  // Notatka to zawsze wiadomość do Ciebie (wzmianka albo odpowiedź) — jak wzmianka.
  if (event.kind === "note") return true;
  const key = chatThreadKey(event.kind, event.entity_id);
  const previous = lastShown.get(key);
  const quiet =
    event.notification_type !== "job_chat_mention" &&
    previous !== undefined &&
    now - previous < CHAT_TOAST_QUIET_MS;
  if (quiet) return false;
  lastShown.set(key, now);
  return true;
}
