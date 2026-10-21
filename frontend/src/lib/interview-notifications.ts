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
  // 0453 (17.10.2026): odpowiedź kandydata na prep i zmiany prepu w parze.
  "prep_candidate_response",
  "prep_candidate_declined",
  "prep_changed",
  "prep_changed_yours",
  "prep_no_response",
  // 0482 (20.10.2026): rozmowa bez Prepu 2 (do DL) i próg pominięć (do HoR).
  "prep2_skipped",
  "prep2_skip_threshold",
  // 0500 (21.10.2026): rozmowa u klienta przełożona albo odwołana — z dymkiem.
  "interview_changed",
] as const;

export type InterviewNotificationType = (typeof INTERVIEW_NOTIFICATION_TYPES)[number];

const TYPE_SET: ReadonlySet<string> = new Set(INTERVIEW_NOTIFICATION_TYPES);

export function isInterviewNotificationType(
  type: string | null | undefined,
): type is InterviewNotificationType {
  return type != null && TYPE_SET.has(type);
}

/**
 * Typy „Kalendarza” bez dymka — tylko licznik ikony (decyzja D6, 17.10.2026):
 * kandydat przyjął / „może”, zmiana prepu w cudzym kalendarzu i przypomnienie
 * o braku odpowiedzi. Dymek zostaje tam, gdzie ktoś ma ruch: odmowa albo inny
 * termin kandydata i zmiana prepu w Twoim kalendarzu.
 */
export const QUIET_INTERVIEW_TYPES: ReadonlySet<string> = new Set([
  "prep_candidate_response",
  "prep_changed",
  "prep_no_response",
  // 0482: informacja o pominiętym Prepie 2 i progu — sam licznik.
  "prep2_skipped",
  "prep2_skip_threshold",
]);

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

/**
 * Link spotkania (Teams) przychodzi z kalendarza Microsoft 365, czyli także
 * z zaproszeń spoza firmy. Otwieramy go tylko, gdy jest zwykłym adresem
 * `https:` — `window.open` nie ma osłony, którą React daje `<a href>`.
 */
export function safeMeetingUrl(url: string | null | undefined): string | null {
  return url && /^https:\/\//i.test(url) ? url : null;
}

/**
 * Tekst dymka po powiadomieniu z gniazda. Terminy od klienta i przypomnienie
 * kalendarza mówią wszystko w treści („3 terminy…”, „Za 15 minut: …”),
 * pozostałe — w tytule („Kandydat wybrał termin”).
 */
export function interviewToastText(notif: {
  notification_type?: string | null;
  title: string;
  message: string;
}): string {
  const fromMessage =
    notif.notification_type === "interview_slots_requested" ||
    notif.notification_type === "interview_scheduled";
  return (fromMessage ? notif.message : notif.title) || notif.title || notif.message;
}

const CALL_TOAST_KEY = "nexus:interview-call-toasted";
const CALL_TOAST_KEEP_MS = 24 * 60 * 60_000;
// Zapas, gdy pamięć przeglądarki jest niedostępna (tryb prywatny, blokada).
const callToastsThisTab = new Set<number>();

/**
 * Czy pokazać dymek „rozmowa u klienta skończyła się” dla tego wydarzenia.
 * Zapamiętuje odpowiedź w `localStorage`, wspólnym dla kart — ta sama rozmowa
 * nie dymi w każdej otwartej karcie ani po odświeżeniu strony.
 */
export function claimCallToast(eventId: number, now: number = Date.now()): boolean {
  if (callToastsThisTab.has(eventId)) return false;
  callToastsThisTab.add(eventId);
  try {
    const raw = window.localStorage.getItem(CALL_TOAST_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    const seen: Record<string, number> = {};
    if (parsed && typeof parsed === "object") {
      for (const [id, at] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof at === "number" && now - at < CALL_TOAST_KEEP_MS) seen[id] = at;
      }
    }
    if (seen[String(eventId)] != null) return false;
    seen[String(eventId)] = now;
    window.localStorage.setItem(CALL_TOAST_KEY, JSON.stringify(seen));
  } catch {
    // Bez pamięci przeglądarki dymek pokaże się raz na kartę.
  }
  return true;
}

/** Tylko do testów: zapomnij dymki pokazane w tej karcie. */
export function resetCallToastsForTests(): void {
  callToastsThisTab.clear();
}
