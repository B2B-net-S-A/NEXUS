// Okienko „Rozmowy” w górnym pasku (13.10.2026) — co pokazać i w której sekcji.
//
// Dwa źródła: przegląd cyklu (`GET /api/interview-cycle`, zadania i agenda
// z flagą `mine`) oraz nieprzeczytane powiadomienia kategorii „Rozmowy”
// (`GET /api/notifications/interviews`). Funkcja jest czysta, a czas liczy
// lokalnie z agendy — „Teraz” i pigułka nie zależą od chwili odpytania serwera.

import type { NotificationResponse } from "@/lib/api";
import {
  TODO_LABELS,
  candidateLabel,
  countdownLabel,
  debriefSummaryLine,
  formatTime,
  pairContext,
  pairKey,
  relativeLabel,
  type AgendaEntry,
  type AgendaKind,
  type CycleItem,
  type CycleOverview,
  type PairInfo,
  type TodoEntry,
  type TodoKind,
} from "@/lib/interview-cycle";
import {
  isInterviewNotificationType,
  parseInterviewLink,
  safeMeetingUrl,
} from "@/lib/interview-notifications";
import { formatNotificationText, notificationOnBehalfLabel } from "@/lib/notification-format";
import { countPl } from "@/lib/plural-pl";

/** Prep albo rozmowa wchodzi do „Teraz” kwadrans przed startem. */
export const STARTING_SOON_MS = 15 * 60_000;
/** Wydarzenie bez końca liczymy jako godzinne. */
const DEFAULT_EVENT_MS = 60 * 60_000;
/** Przypomnienie starsze niż doba jest na pewno po wydarzeniu (sufit wyprzedzenia). */
const REMINDER_STALE_MS = 24 * 60 * 60_000;

/**
 * Początek wydarzenia z treści przypomnienia: serwer pisze „Za 15 minut: …”
 * z realną liczbą minut do startu (`calendar._minutes_pl`: minutę / minuty /
 * minut). Bez liczby w treści — `null`, a przypomnienie żyje najwyżej dobę.
 */
function reminderStartMs(message: string | null | undefined, createdMs: number): number | null {
  const lead = /^Za (\d+) minut/.exec(message ?? "");
  return lead ? createdMs + Number(lead[1]) * 60_000 : null;
}

const TZ = "Europe/Warsaw";

export type WindowSection = "now" | "waiting" | "news";
export type WindowIcon = "phone" | "video" | "calendar" | "slots" | "confirm" | "alert" | "note";
export type WindowTone = "urgent" | "warn" | "info";

export interface InterviewWindowRow {
  key: string;
  section: WindowSection;
  /** Nazwisko kandydata, a gdy para jest nieznana — tytuł powiadomienia. */
  title: string;
  /** „Klient · stanowisko”. */
  context: string | null;
  /** Co się dzieje albo co jest do zrobienia; puste, gdy para jest nieznana
   *  (wtedy `title` niesie tytuł powiadomienia, a `detail` jego treść). */
  status: string;
  detail: string | null;
  icon: WindowIcon;
  tone: WindowTone;
  /** Plakietka „pilne” (brak prepu na dobę przed rozmową u klienta). */
  urgent: boolean;
  /** Zadanie do `actionForTodo` — przycisk akcji w wierszu. */
  todo: TodoEntry | null;
  /** Link Teams prepu — przycisk „Dołącz”. */
  joinUrl: string | null;
  /** Dokąd prowadzi klik w wiersz. */
  href: string;
  /** Nieprzeczytane powiadomienia zwinięte w ten wiersz (kropka „nowe”). */
  unreadIds: number[];
  /** Pozostałe zadania tej pary, których wiersz nie pokazuje. */
  more: number;
  /** Czas powiadomienia (sekcja „Nowe”). */
  at: string | null;
  onBehalfOf: string | null;
  /** Wydarzenie wiersza „Teraz” — do zwijania przypomnień kalendarza. */
  eventId: number | null;
  /** Koniec okna telefonu po rozmowie — odliczanie pigułki. */
  callDeadline: string | null;
}

export interface InterviewWindow {
  now: InterviewWindowRow[];
  waiting: InterviewWindowRow[];
  news: InterviewWindowRow[];
  /** Licznik na ikonie: wiersze wszystkich sekcji. */
  count: number;
  /** Czerwony licznik: coś dzieje się teraz albo zadanie jest pilne. */
  urgent: boolean;
  /** Telefon po rozmowie u klienta — pigułka zamiast ikony. */
  pill: { name: string; minutesLeft: number; row: InterviewWindowRow } | null;
  /** Stopka „Dziś jeszcze: …”. */
  today: { time: string; label: string; name: string } | null;
}

const STARTING_LABELS: Record<"prep" | "prep2" | "interview", string> = {
  prep: "Prep 1",
  prep2: "Prep 2",
  interview: "Rozmowa u klienta",
};

const TODO_ICONS: Partial<Record<TodoKind, WindowIcon>> = {
  debrief_overdue: "phone",
  questions_missing: "note",
  slots_pick: "slots",
  slots_confirm: "confirm",
  slots_reply: "confirm",
  prep_missing: "video",
  prep2_missing: "video",
  prep_late: "video",
  prep_weak: "alert",
  prep_unrecorded: "alert",
  precall_due: "phone",
};

/** Zadania, których okienko nie bierze z serwera: telefon po rozmowie liczymy
 *  lokalnie z agendy, a brak terminów od klienta to stan do 30 dni, na który
 *  Delivery Lead nie ma ruchu — licznik na ikonie nigdy by nie gasł. */
const SKIPPED_TODOS: ReadonlySet<TodoKind> = new Set(["call_now", "slots_missing"]);

function isStartingKind(kind: AgendaKind): kind is "prep" | "prep2" | "interview" {
  return kind === "prep" || kind === "prep2" || kind === "interview";
}

function dayKey(date: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

/** „dziś 15:00” / „jutro 10:00” / „czw., 15.10, 11:00”. */
export function whenLabel(iso: string, now: Date): string {
  const date = new Date(iso);
  const time = formatTime(iso);
  const key = dayKey(date);
  if (key === dayKey(now)) return `dziś ${time}`;
  if (key === dayKey(new Date(now.getTime() + 86_400_000))) return `jutro ${time}`;
  const day = new Intl.DateTimeFormat("pl-PL", {
    timeZone: TZ,
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  }).format(date);
  return `${day}, ${time}`;
}

/** „po terminie 12 min” / „po terminie 5 h” / „po terminie 20 dni”. */
export function overdueLabel(iso: string, now: Date): string {
  const minutes = Math.max(1, Math.ceil((now.getTime() - new Date(iso).getTime()) / 60_000));
  if (minutes < 120) return `po terminie ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `po terminie ${hours} h`;
  return `po terminie ${countPl(Math.floor(hours / 24), "dzień", "dni", "dni")}`;
}

/** „Marta Wilk” → „M. Wilk” (pigułka w pasku jest wąska). */
export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length < 2 || name.startsWith("Kandydat #")) return name;
  return `${parts[0].charAt(0)}. ${parts.slice(1).join(" ")}`;
}

function cycleHref(pair: Pick<PairInfo, "candidate_id" | "job_id">): string {
  return `/calendar?cycle=${pairKey(pair)}`;
}

function pairOf(entry: PairInfo): PairInfo {
  return {
    candidate_id: entry.candidate_id,
    candidate_name: entry.candidate_name,
    candidate_email: entry.candidate_email,
    job_id: entry.job_id,
    job_title: entry.job_title,
    client_id: entry.client_id,
    client_name: entry.client_name,
  };
}

function baseRow(
  section: WindowSection,
  key: string,
  pair: PairInfo,
): Omit<InterviewWindowRow, "status" | "detail" | "icon" | "tone"> {
  return {
    key,
    section,
    title: candidateLabel(pair),
    context: pairContext(pair),
    urgent: false,
    todo: null,
    joinUrl: null,
    href: cycleHref(pair),
    unreadIds: [],
    more: 0,
    at: null,
    onBehalfOf: null,
    eventId: null,
    callDeadline: null,
  };
}

function callTodo(entry: AgendaEntry, kind: "call_now" | "debrief_overdue"): TodoEntry {
  return {
    ...pairOf(entry),
    kind,
    priority: kind === "call_now" ? 0 : 1,
    due: entry.end,
    event_id: entry.event_id,
    slot_request_id: null,
    mine: true,
  };
}

function todoDetail(todo: TodoEntry, item: CycleItem | undefined, now: Date): string | null {
  switch (todo.kind) {
    case "slots_pick": {
      const count = item?.slot_request?.slots.length ?? 0;
      const parts = [
        count > 0 ? `${countPl(count, "termin", "terminy", "terminów")} od klienta` : null,
        todo.due ? `odpowiedz do ${whenLabel(todo.due, now)}` : null,
      ];
      return parts.filter(Boolean).join(" · ") || null;
    }
    case "slots_confirm":
      return todo.due ? `kandydat wybrał ${whenLabel(todo.due, now)}` : null;
    case "slots_reply":
      return todo.due ? `rozmowa w kalendarzu ${whenLabel(todo.due, now)} — potwierdź klientowi` : null;
    case "prep_late":
      return "przełóż przed rozmowę";
    case "questions_missing":
      // `due` to doba od przesunięcia na „Rozmowę u klienta”, nie termin rozmowy.
      return "rozmowy nie ma w kalendarzu — zapisz, o co pytał klient";
    default:
      return todo.due ? `rozmowa u klienta ${whenLabel(todo.due, now)}` : null;
  }
}

function debriefExists(item: CycleItem | undefined, eventId: number | null): boolean {
  return Boolean(item?.debrief) && (eventId == null || item?.interview_event_id === eventId);
}

export function buildInterviewWindow({
  overview,
  notifications,
  now,
}: {
  overview: CycleOverview | null | undefined;
  notifications: readonly NotificationResponse[];
  now: Date;
}): InterviewWindow {
  const nowMs = now.getTime();
  const items = overview?.items ?? [];
  const itemByPair = new Map(items.map((item) => [pairKey(item), item]));
  const agenda = overview?.agenda ?? [];
  // Stary serwer i zasiane dane harnessów nie niosą `mine` — wtedy nic nie
  // jest „moje” i okienko pokazuje same powiadomienia.
  const myAgenda = agenda.filter((entry) => entry.mine === true);
  const myTodos = (overview?.todos ?? []).filter((todo) => todo.mine === true);

  const rowByPair = new Map<string, InterviewWindowRow>();
  const nowRows: InterviewWindowRow[] = [];
  const waiting: InterviewWindowRow[] = [];
  const place = (row: InterviewWindowRow, pair: PairInfo) => {
    const existing = rowByPair.get(pairKey(pair));
    if (existing) {
      existing.more += 1;
      return;
    }
    rowByPair.set(pairKey(pair), row);
    (row.section === "now" ? nowRows : waiting).push(row);
  };

  // „Teraz”: telefon po rozmowie u klienta, potem to, co zaczyna się albo trwa.
  const calls = myAgenda.filter((e) => e.kind === "call" && !e.done && e.end != null);
  for (const entry of calls) {
    const start = new Date(entry.start).getTime();
    const end = new Date(entry.end as string).getTime();
    if (start > nowMs || nowMs > end) continue;
    place(
      {
        ...baseRow("now", `call:${entry.event_id}`, entry),
        status: "Zadzwoń po rozmowie u klienta",
        detail: countdownLabel(entry.end as string, now),
        icon: "phone",
        tone: "urgent",
        todo: callTodo(entry, "call_now"),
        eventId: entry.event_id,
        callDeadline: entry.end,
      },
      entry,
    );
  }
  const starting = myAgenda
    .filter((e) => isStartingKind(e.kind))
    .sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());
  for (const entry of starting) {
    const start = new Date(entry.start).getTime();
    const end = entry.end ? new Date(entry.end).getTime() : start + DEFAULT_EVENT_MS;
    if (nowMs < start - STARTING_SOON_MS || nowMs >= end) continue;
    const label = STARTING_LABELS[entry.kind as "prep" | "prep2" | "interview"];
    place(
      {
        ...baseRow("now", `event:${entry.event_id}`, entry),
        status: nowMs < start ? `${label} ${relativeLabel(entry.start, now)}` : `${label} trwa`,
        detail: [formatTime(entry.start), safeMeetingUrl(entry.online_meeting_url) ? "Teams" : null]
          .filter(Boolean)
          .join(", "),
        icon: entry.kind === "interview" ? "calendar" : "video",
        tone: "urgent",
        joinUrl: entry.kind === "interview" ? null : safeMeetingUrl(entry.online_meeting_url),
        eventId: entry.event_id,
      },
      entry,
    );
  }

  // „Czeka na Ciebie”: zaległy debrief (z agendy) i zadania z serwera.
  for (const entry of calls) {
    if (nowMs <= new Date(entry.end as string).getTime()) continue;
    place(
      {
        ...baseRow("waiting", `debrief:${entry.event_id}`, entry),
        status: TODO_LABELS.debrief_overdue,
        detail: overdueLabel(entry.end as string, now),
        icon: "phone",
        tone: "urgent",
        todo: callTodo(entry, "debrief_overdue"),
      },
      entry,
    );
  }
  const agendaCallEvents = new Set(myAgenda.filter((e) => e.kind === "call").map((e) => e.event_id));
  for (const todo of myTodos) {
    if (SKIPPED_TODOS.has(todo.kind)) continue;
    if (todo.kind === "debrief_overdue") {
      // Policzony wyżej z agendy. Zadanie z serwera zostaje dla rozmowy
      // starszej niż okno agendy (14 dni) — ono nie ma limitu wieku, a bez
      // tego wiersz gasłby tak, jakby debrief zapisano.
      if (agendaCallEvents.has(todo.event_id)) continue;
      place(
        {
          ...baseRow("waiting", `debrief:${todo.event_id}`, todo),
          status: TODO_LABELS.debrief_overdue,
          detail: todo.due ? overdueLabel(todo.due, now) : null,
          icon: "phone",
          tone: "urgent",
          todo,
        },
        todo,
      );
      continue;
    }
    place(
      {
        ...baseRow("waiting", `todo:${todo.kind}:${pairKey(todo)}`, todo),
        status: TODO_LABELS[todo.kind],
        detail: todoDetail(todo, itemByPair.get(pairKey(todo)), now),
        icon: TODO_ICONS[todo.kind] ?? "calendar",
        tone: "warn",
        urgent: Boolean(todo.urgent),
        todo,
      },
      todo,
    );
  }

  // „Nowe”: nieprzeczytane powiadomienia. Sygnał zadania zwija się w kropkę
  // przy wierszu pary; informacja ma zawsze własny wiersz.
  const overviewAt = overview && !overview.truncated ? new Date(overview.generated_at).getTime() : null;
  const news: InterviewWindowRow[] = [];
  for (const notif of notifications) {
    if (!isInterviewNotificationType(notif.notification_type)) continue;
    const target = parseInterviewLink(notif.link);
    const event =
      target.eventId != null ? agenda.find((e) => e.event_id === target.eventId && e.kind !== "call") : undefined;
    const key = target.pair
      ? `${target.pair.candidateId}-${target.pair.jobId}`
      : event
        ? pairKey(event)
        : null;
    const item = key ? itemByPair.get(key) : undefined;
    const pairRow = key ? rowByPair.get(key) : undefined;
    const createdMs = notif.created_at ? new Date(notif.created_at).getTime() : nowMs;
    // Stan pary wolno czytać tylko z przeglądu świeższego niż powiadomienie:
    // lista powiadomień wraca przed przeglądem i stary stan schowałby świeży sygnał.
    const fresh = item != null && overviewAt != null && overviewAt > createdMs;
    const fold = () => pairRow?.unreadIds.push(notif.id);
    const pair: PairInfo | undefined = item ?? event;

    let status = formatNotificationText(notif.title);
    let detail: string | null = null;
    let icon: WindowIcon = "calendar";
    switch (notif.notification_type) {
      case "interview_slots_requested":
        if (fresh && item?.slot_request?.status !== "awaiting_recruiter") continue;
        if (pairRow) {
          fold();
          continue;
        }
        icon = "slots";
        break;
      case "interview_slot_chosen":
        if (fresh && item?.slot_request?.status !== "awaiting_dl") continue;
        if (pairRow) {
          fold();
          continue;
        }
        icon = "confirm";
        break;
      case "post_interview_t15":
      case "post_interview_t45":
        if (fresh && debriefExists(item, target.eventId)) continue;
        if (pairRow) {
          fold();
          continue;
        }
        icon = "phone";
        break;
      case "post_interview_t2h_escalation":
        if (fresh && debriefExists(item, target.eventId)) continue;
        if (pair) status = "Brak debriefu 2 h po rozmowie u klienta";
        icon = "alert";
        break;
      case "prep_attention":
        if (pairRow) {
          fold();
          continue;
        }
        icon = "alert";
        break;
      // 0453: odpowiedź kandydata i zmiany prepu — informacja, własny wiersz.
      case "prep_candidate_declined":
      case "prep_no_response":
        icon = "alert";
        break;
      case "prep_candidate_response":
        icon = "confirm";
        break;
      case "prep_changed":
      case "prep_changed_yours":
        icon = "video";
        break;
      // 0482: rozmowa bez Prepu 2 (telefon zamiast prepu) i próg pominięć.
      case "prep2_skipped":
        icon = "phone";
        break;
      case "prep2_skip_threshold":
        icon = "alert";
        break;
      // 0500: rozmowa u klienta przełożona albo odwołana — tytuł mówi co i kiedy.
      case "interview_changed":
        icon = "calendar";
        break;
      // 0506: ocena prepu gotowa — tytuł niesie poziom i wynik.
      case "prep_review_ready":
        icon = "video";
        break;
      case "interview_scheduled": {
        // Po starcie wydarzenia przypomnienie nic już nie mówi. Wydarzenie
        // spoza agendy cyklu (screening, zwykła rozmowa, termin) nie ma tu
        // daty — bierzemy ją z treści; do 13.10.2026 takie wiersze wisiały dobę.
        const startsAt = event
          ? new Date(event.start).getTime()
          : (reminderStartMs(notif.message, createdMs) ?? createdMs + REMINDER_STALE_MS);
        if (startsAt <= nowMs) continue;
        if (pairRow && pairRow.eventId != null && pairRow.eventId === target.eventId) {
          fold();
          continue;
        }
        if (event && isStartingKind(event.kind)) {
          status = `${STARTING_LABELS[event.kind]} ${whenLabel(event.start, now)}`;
        } else {
          status = formatNotificationText(notif.message);
        }
        icon = event && event.kind !== "interview" ? "video" : "calendar";
        break;
      }
      case "interview_slot_confirmed": {
        const at = item?.steps.find((s) => s.key === "interview")?.at;
        if (pair) status = "Termin potwierdzony u klienta";
        detail = at ? whenLabel(at, now) : null;
        icon = "confirm";
        break;
      }
      case "interview_debrief_saved":
        if (pair) status = "Debrief zapisany";
        // Warunek kandydata (stawka, druga oferta) to najważniejsza informacja dla DL.
        detail =
          [
            item?.debrief ? debriefSummaryLine(item.debrief) : "",
            item?.debrief?.acceptance_condition ? `warunek: ${item.debrief.acceptance_condition}` : "",
          ]
            .filter(Boolean)
            .join(" · ") || formatNotificationText(notif.message);
        icon = "note";
        break;
    }
    news.push({
      key: `notif:${notif.id}`,
      section: "news",
      title: pair ? candidateLabel(pair) : formatNotificationText(notif.title),
      context: pair ? pairContext(pair) : null,
      status: pair ? status : "",
      detail: pair ? detail : formatNotificationText(notif.message),
      icon,
      tone: "info",
      urgent: false,
      todo: null,
      joinUrl: null,
      href: notif.link || (pair ? cycleHref(pair) : "/calendar"),
      unreadIds: [notif.id],
      more: 0,
      at: notif.created_at,
      onBehalfOf: notificationOnBehalfLabel(notif),
      eventId: target.eventId,
      callDeadline: null,
    });
  }

  const callRow = nowRows.find((row) => row.callDeadline != null);
  const today = dayKey(now);
  const shownEvents = new Set(nowRows.map((row) => row.eventId));
  const next = starting.find(
    (e) =>
      new Date(e.start).getTime() > nowMs &&
      dayKey(new Date(e.start)) === today &&
      !shownEvents.has(e.event_id),
  );

  return {
    now: nowRows,
    waiting,
    news,
    count: nowRows.length + waiting.length + news.length,
    urgent: nowRows.length > 0 || waiting.some((row) => row.urgent),
    pill: callRow
      ? {
          name: shortName(callRow.title),
          minutesLeft: Math.max(
            0,
            Math.ceil((new Date(callRow.callDeadline as string).getTime() - nowMs) / 60_000),
          ),
          row: callRow,
        }
      : null,
    today: next
      ? {
          time: formatTime(next.start),
          label: STARTING_LABELS[next.kind as "prep" | "prep2" | "interview"],
          name: candidateLabel(next),
        }
      : null,
  };
}

/**
 * Najbliższa chwila, w której okienko zmieni się samo (wydarzenie wchodzi do
 * „Teraz”, kończy się, mija okno telefonu) — kontener budzi się wtedy raz,
 * zamiast przeliczać co sekundę.
 */
export function nextWindowBoundary(overview: CycleOverview | null | undefined, now: Date): number | null {
  const nowMs = now.getTime();
  let next: number | null = null;
  const consider = (ms: number) => {
    if (ms > nowMs && (next == null || ms < next)) next = ms;
  };
  for (const entry of overview?.agenda ?? []) {
    if (entry.mine !== true) continue;
    const start = new Date(entry.start).getTime();
    consider(start);
    if (entry.end) consider(new Date(entry.end).getTime());
    if (isStartingKind(entry.kind)) {
      consider(start - STARTING_SOON_MS);
      if (!entry.end) consider(start + DEFAULT_EVENT_MS);
    }
  }
  return next;
}
