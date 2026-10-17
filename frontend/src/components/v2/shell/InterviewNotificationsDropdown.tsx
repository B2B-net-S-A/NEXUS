"use client";

import {
  AlertTriangle,
  Calendar,
  CalendarCheck,
  CalendarClock,
  CheckCheck,
  FileText,
  Loader2,
  Phone,
  Settings2,
  Video,
  type LucideIcon,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useHasInterviewsWindow } from "@/hooks/useHasInterviewsWindow";
import type { WsNotification } from "@/hooks/useNotifications";
import type { NotificationResponse } from "@/lib/api";
import { useInterviewCycle } from "@/lib/api/interviewCycle";
import {
  useInterviewNotifications,
  useMarkInterviewNotificationsRead,
} from "@/lib/api/interviewNotifications";
import {
  TODO_ACTIONS,
  actionForTodo,
  type CycleAction,
  type CycleScope,
} from "@/lib/interview-cycle";
import {
  INTERVIEW_NOTIFY_EVENT,
  QUIET_INTERVIEW_TYPES,
  OPEN_INTERVIEWS_WINDOW_EVENT,
  claimCallToast,
  interviewToastText,
  parseInterviewLink,
  safeMeetingUrl,
} from "@/lib/interview-notifications";
import {
  buildInterviewWindow,
  nextWindowBoundary,
  type InterviewWindow,
  type InterviewWindowRow,
  type WindowIcon,
  type WindowTone,
} from "@/lib/interview-window";
import { MY_NOTIFICATIONS_SETTINGS_HREF } from "@/lib/notification-topics";
import { formatNotificationText, notificationTimeAgo } from "@/lib/notification-format";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { hasSectionAccess } from "@/lib/section-access";
import { cn } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

// Okna akcji (debrief, terminy, prep) dochodzą dopiero po kliknięciu — pasek
// stoi na każdej stronie i nie może ciągnąć ich w swojej paczce.
const InterviewActionDialogs = dynamic(() => import("./InterviewActionDialogs"), {
  ssr: false,
});

const CALENDAR_HREF = "/calendar";
const TOAST_MS = 8_000;
/** Odliczania („zostało 18 min”) odświeżają się co pół minuty. */
const TICK_MS = 30_000;
/** Pasek nie odpytuje cyklu przy każdym powrocie do karty — odświeża go gniazdo. */
const TOPBAR_STALE_MS = 2 * 60_000;
const REFRESH_ON_OPEN_MS = 30_000;
const NO_NOTIFICATIONS: NotificationResponse[] = [];

function countLabel(n: number): string {
  return n > 99 ? "99+" : String(n);
}

const ICONS: Record<WindowIcon, LucideIcon> = {
  phone: Phone,
  video: Video,
  calendar: Calendar,
  slots: CalendarClock,
  confirm: CalendarCheck,
  alert: AlertTriangle,
  note: FileText,
};

const TONES: Record<WindowTone, string> = {
  urgent: "bg-destructive-muted text-destructive-muted-foreground",
  warn: "bg-warning-muted text-warning-muted-foreground",
  info: "bg-primary/10 text-primary",
};

const SECTIONS: { key: "now" | "waiting" | "news"; title: string }[] = [
  { key: "now", title: "Teraz" },
  { key: "waiting", title: "Czeka na Ciebie" },
  { key: "news", title: "Nowe" },
];

const ROW_ACTION_CLASS = "ml-auto h-7 shrink-0 px-2.5 text-xs";

export type InterviewsPanelState = "loading" | "error" | "ready";

export interface InterviewsPanelProps {
  state: InterviewsPanelState;
  view: InterviewWindow;
  /** Jedno ze źródeł nie odpowiedziało — reszta jest pokazana, ale niepełna. */
  failed?: "tasks" | "news" | null;
  /** Są własne nieprzeczytane powiadomienia — pokaż „Oznacz nowe”. */
  canMarkNews: boolean;
  markingAll?: boolean;
  /** Napis przycisku akcji wiersza albo `null`, gdy wiersz tylko informuje. */
  actionLabel: (row: InterviewWindowRow) => string | null;
  onOpenRow: (row: InterviewWindowRow) => void;
  onAction: (row: InterviewWindowRow) => void;
  onMarkNewsRead: () => void;
  onRetry: () => void;
  onOpenSettings: () => void;
  onOpenCalendar: () => void;
}

/** Treść okienka „Rozmowy” — bez zapytań, dane w propsach (także w harnessie). */
export function InterviewsPanel({
  state,
  view,
  failed = null,
  canMarkNews,
  markingAll = false,
  actionLabel,
  onOpenRow,
  onAction,
  onMarkNewsRead,
  onRetry,
  onOpenSettings,
  onOpenCalendar,
}: InterviewsPanelProps) {
  const empty = view.count === 0;
  return (
    <div className="flex max-h-[min(600px,calc(100dvh-6rem))] flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2">
        <h2 className="text-sm font-semibold text-foreground">Rozmowy u klienta</h2>
        <div className="flex items-center gap-1">
          {state === "ready" && canMarkNews ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onMarkNewsRead}
              disabled={markingAll}
              aria-label="Oznacz nowe powiadomienia jako przeczytane"
              className="h-8 gap-1.5 px-2 text-xs"
            >
              <CheckCheck className="h-3.5 w-3.5" aria-hidden />
              Oznacz nowe
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="icon"
            onClick={onOpenSettings}
            aria-label="Ustawienia powiadomień"
            className="h-8 w-8"
          >
            <Settings2 className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </div>

      {state === "loading" ? (
        <div className="flex items-center justify-center gap-2 px-4 py-10 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Wczytuję rozmowy…
        </div>
      ) : state === "error" ? (
        <div role="alert" className="px-6 py-8 text-center">
          <p className="text-sm font-medium text-foreground">Nie udało się wczytać rozmów.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            To nie znaczy, że nic nie czeka. Spróbuj ponownie albo otwórz kalendarz.
          </p>
          <Button variant="outline" size="sm" onClick={onRetry} className="mt-3">
            Ponów
          </Button>
        </div>
      ) : (
        <div className="relative min-h-0 flex-1 overflow-y-auto">
          {failed ? (
            <div
              role="alert"
              className="flex items-center justify-between gap-3 border-b border-border bg-warning-muted px-4 py-2 text-xs text-warning-muted-foreground"
            >
              <span className="min-w-0">
                {failed === "tasks"
                  ? "Nie udało się wczytać zadań — widzisz same powiadomienia."
                  : "Nie udało się wczytać nowych powiadomień — widzisz same zadania."}
              </span>
              <button
                type="button"
                onClick={onRetry}
                className="shrink-0 font-semibold underline underline-offset-2"
              >
                Ponów
              </button>
            </div>
          ) : null}
          {empty && !failed ? (
            <div className="px-6 py-8 text-center">
              <p className="text-sm font-medium text-foreground">
                Nic nie czeka w sprawie rozmów u klienta.
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Gdy klient poda terminy albo zbliży się prep lub rozmowa, zobaczysz to tutaj.
              </p>
            </div>
          ) : null}
          {SECTIONS.map(({ key, title }) =>
            view[key].length > 0 ? (
              <section key={key} aria-label={title}>
                <h3
                  className={cn(
                    "border-b border-border bg-muted/50 px-4 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide",
                    key === "now" ? "text-destructive-muted-foreground" : "text-muted-foreground",
                  )}
                >
                  {title}
                </h3>
                <ul className="divide-y divide-border border-b border-border">
                  {view[key].map((row) => (
                    <InterviewRow
                      key={row.key}
                      row={row}
                      label={actionLabel(row)}
                      onOpen={onOpenRow}
                      onAction={onAction}
                    />
                  ))}
                </ul>
              </section>
            ) : null,
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2 text-xs text-muted-foreground">
        <span className="min-w-0 truncate">
          {state === "ready" && view.today
            ? `Dziś jeszcze: ${view.today.time} ${view.today.label} · ${view.today.name}`
            : ""}
        </span>
        <button
          type="button"
          onClick={onOpenCalendar}
          className="shrink-0 font-medium text-primary hover:underline"
        >
          Kalendarz
        </button>
      </div>
    </div>
  );
}

function InterviewRow({
  row,
  label,
  onOpen,
  onAction,
}: {
  row: InterviewWindowRow;
  label: string | null;
  onOpen: (row: InterviewWindowRow) => void;
  onAction: (row: InterviewWindowRow) => void;
}) {
  const Icon = ICONS[row.icon];
  const isNew = row.unreadIds.length > 0;
  return (
    <li className={cn("flex gap-3 px-4 py-2", isNew && "bg-primary/5")}>
      <span
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          TONES[row.tone],
        )}
      >
        <Icon className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-h-7 items-center gap-2">
          <button
            type="button"
            onClick={() => onOpen(row)}
            className="min-w-0 truncate text-left text-sm font-semibold text-foreground hover:underline focus-visible:underline focus-visible:outline-hidden"
          >
            {row.title}
          </button>
          {row.urgent ? (
            <span className="shrink-0 rounded-full bg-destructive-muted px-1.5 text-xs font-semibold text-destructive-muted-foreground">
              pilne
            </span>
          ) : null}
          {isNew && row.section !== "news" ? (
            <span
              role="img"
              aria-label="nowe"
              className="h-2 w-2 shrink-0 rounded-full bg-primary"
            />
          ) : null}
          {row.joinUrl ? (
            <Button asChild size="sm" className={ROW_ACTION_CLASS}>
              <a href={row.joinUrl} target="_blank" rel="noopener noreferrer">
                Dołącz
              </a>
            </Button>
          ) : label ? (
            <Button
              size="sm"
              variant={row.section === "now" ? "primary" : "outline"}
              onClick={() => onAction(row)}
              className={ROW_ACTION_CLASS}
            >
              {label}
            </Button>
          ) : row.at ? (
            <span className="ml-auto shrink-0 text-xs text-muted-foreground">
              {notificationTimeAgo(row.at)}
            </span>
          ) : null}
        </div>
        {row.context ? (
          <p className="truncate text-xs text-muted-foreground">{row.context}</p>
        ) : null}
        <p className="mt-0.5 text-xs text-foreground">
          {row.status ? (
            <span
              className={cn(
                "font-semibold",
                row.section === "now" && "text-destructive-muted-foreground",
              )}
            >
              {row.status}
            </span>
          ) : null}
          {row.status && row.detail ? " · " : null}
          {row.detail}
        </p>
        {row.more > 0 || row.onBehalfOf ? (
          <p className="mt-0.5 text-xs text-muted-foreground">
            {[row.onBehalfOf, row.more > 0 ? `+${row.more} w kalendarzu` : null]
              .filter(Boolean)
              .join(" · ")}
          </p>
        ) : null}
      </div>
    </li>
  );
}

export interface InterviewsTopbarButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  count: number;
  /** Czerwony licznik: coś dzieje się teraz albo zadanie jest pilne. */
  urgent: boolean;
  open: boolean;
  /** Telefon po rozmowie u klienta — ikona zamienia się w pigułkę z odliczaniem. */
  pill: { name: string; minutesLeft: number } | null;
}

/** Ikona „Rozmowy” w górnym pasku — wygląd jak „Czaty” i dzwonek obok. */
export function InterviewsTopbarButton({
  count,
  urgent,
  open,
  pill,
  className,
  ref,
  ...props
}: InterviewsTopbarButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  const label = pill
    ? `Rozmowy u klienta — zadzwoń: ${pill.name}, zostało ${pill.minutesLeft} min`
    : count > 0
      ? `Rozmowy u klienta — sprawy do załatwienia: ${count}`
      : "Rozmowy u klienta";
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title="Kalendarz — rozmowy u klienta i prepy"
      className={cn(
        "relative transition-colors",
        pill
          ? "flex h-8 items-center gap-1.5 rounded-full bg-destructive-muted px-2.5 text-xs font-semibold text-destructive-muted-foreground hover:bg-destructive-muted/70"
          : "rounded-lg p-2",
        !pill &&
          (open
            ? "bg-primary/10 text-primary"
            : "text-muted-foreground hover:bg-muted hover:text-foreground"),
        className,
      )}
      {...props}
    >
      {pill ? (
        <>
          <Phone className="h-4 w-4 shrink-0" aria-hidden />
          {/* Pełny tekst dopiero od 1536 px — przy 1280 px z przypiętym menu
              pasek nie ma miejsca na nazwisko. */}
          <span className="hidden whitespace-nowrap 2xl:inline">Zadzwoń: {pill.name} ·</span>
          <span className="whitespace-nowrap tabular-nums">{pill.minutesLeft} min</span>
        </>
      ) : (
        <CalendarClock className="h-5 w-5" aria-hidden />
      )}
      {count > 0 ? (
        <span
          className={cn(
            "absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-xs font-bold tabular-nums",
            urgent ? "bg-destructive text-white" : "bg-primary text-primary-foreground",
          )}
        >
          {countLabel(count)}
        </span>
      ) : null}
    </button>
  );
}

/**
 * Okienko „Rozmowy” w górnym pasku (13.10.2026): rozmowy u klienta i prepy —
 * co dzieje się teraz, co czeka na osobę i co nowego przyszło. Dzwonek tych
 * powiadomień już nie pokazuje. Ikonę widzi ten, kto widzi „Kalendarz” w menu.
 */
export function InterviewNotificationsDropdown() {
  return useHasInterviewsWindow() ? <InterviewNotificationsWindow /> : null;
}

function InterviewNotificationsWindow() {
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const { showActionToast } = useToast();
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState<CycleAction | null>(null);
  const [now, setNow] = useState(() => new Date());

  // Ten sam zakres co ekran „Rozmowy u klienta” i kafel „Dziś” — jedno zapytanie
  // obsługuje wszystkie trzy, a „moje” zadania wskazuje serwer (`mine`).
  const scope: CycleScope = hasRole(user, "delivery_lead") ? "jobs" : "mine";
  const cycle = useInterviewCycle(scope, {
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
    staleTime: TOPBAR_STALE_MS,
  });
  const news = useInterviewNotifications();
  const markRead = useMarkInterviewNotificationsRead();
  const overview = cycle.data;
  const notifications = news.data?.items ?? NO_NOTIFICATIONS;

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), TICK_MS);
    return () => clearInterval(id);
  }, []);
  // Dokładna chwila zmiany (koniec rozmowy, kwadrans przed prepem) — bez niej
  // telefon po rozmowie pojawiałby się z opóźnieniem do pół minuty.
  useEffect(() => {
    const next = nextWindowBoundary(overview, new Date());
    if (next == null) return;
    const id = setTimeout(
      () => setNow(new Date()),
      Math.min(Math.max(next - Date.now(), 0) + 500, 2_000_000_000),
    );
    return () => clearTimeout(id);
  }, [overview, now]);

  const view = useMemo(
    () => buildInterviewWindow({ overview, notifications, now }),
    [overview, notifications, now],
  );

  // Lustro `canManageSlots` z ekranu „Rozmowy u klienta”: terminy od klienta
  // dodaje i potwierdza Delivery Lead albo nadzór z zapisem w Pipeline.
  const canManageSlots =
    hasRole(user, "admin", "head_of_recruitment", "delivery_lead") &&
    hasSectionAccess(user, "pipeline", "write");
  const actionFor = (row: InterviewWindowRow): CycleAction | null => {
    if (!row.todo) return null;
    const found = actionForTodo(row.todo, overview?.items ?? []);
    if (!found) return null;
    if ((found.type === "confirm" || found.type === "add_slots") && !canManageSlots) return null;
    return found;
  };

  const markRowRead = (row: InterviewWindowRow) => {
    if (row.unreadIds.length > 0) markRead.mutate(row.unreadIds);
  };
  const openRow = (row: InterviewWindowRow) => {
    markRowRead(row);
    setOpen(false);
    router.push(row.href);
  };
  const runAction = (row: InterviewWindowRow) => {
    const found = actionFor(row);
    if (!found) return;
    markRowRead(row);
    setOpen(false);
    setAction(found);
  };

  const refetchCycle = cycle.refetch;
  const cycleUpdatedAt = cycle.dataUpdatedAt;
  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (!next) return;
    setNow(new Date());
    if (Date.now() - cycleUpdatedAt > REFRESH_ON_OPEN_MS) void refetchCycle();
  };

  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener(OPEN_INTERVIEWS_WINDOW_EVENT, handler);
    return () => window.removeEventListener(OPEN_INTERVIEWS_WINDOW_EVENT, handler);
  }, []);

  // Dymek po powiadomieniu z gniazda: przypomnienie przed prepem prowadzi
  // prosto do Teams, reszta otwiera okienko. Bez dymka, gdy okienko jest otwarte.
  const liveRef = useRef({ open, overview });
  liveRef.current = { open, overview };
  useEffect(() => {
    const handler = (event: Event) => {
      const notif = (event as CustomEvent<WsNotification>).detail;
      if (!notif || liveRef.current.open) return;
      if (notif.notification_type && QUIET_INTERVIEW_TYPES.has(notif.notification_type)) return;
      const { eventId } = parseInterviewLink(notif.link);
      const joinUrl =
        notif.notification_type === "interview_scheduled" && eventId != null
          ? safeMeetingUrl(
              liveRef.current.overview?.agenda.find(
                (entry) => entry.event_id === eventId && entry.online_meeting_url,
              )?.online_meeting_url,
            )
          : null;
      showActionToast(formatNotificationText(interviewToastText(notif)), {
        actionLabel: joinUrl ? "Dołącz" : "Pokaż",
        durationMs: TOAST_MS,
        onAction: () => {
          if (joinUrl) window.open(joinUrl, "_blank", "noopener,noreferrer");
          else setOpen(true);
        },
      });
    };
    window.addEventListener(INTERVIEW_NOTIFY_EVENT, handler);
    return () => window.removeEventListener(INTERVIEW_NOTIFY_EVENT, handler);
  }, [showActionToast]);

  // Koniec rozmowy u klienta nie ma zdarzenia z serwera (pierwsze przychodzi
  // po 15 minutach) — dymek wychodzi z lokalnie policzonego wiersza „Teraz”.
  const callRow = view.pill?.row ?? null;
  const callRowRef = useRef(callRow);
  callRowRef.current = callRow;
  const callEventId = callRow?.todo?.event_id ?? null;
  useEffect(() => {
    const row = callRowRef.current;
    if (callEventId == null || !row?.todo || !claimCallToast(callEventId)) return;
    const who = row.todo.client_name ? `${row.title} (${row.todo.client_name})` : row.title;
    const todo = row.todo;
    showActionToast(`${who}: rozmowa u klienta skończyła się. Na telefon ${row.detail}.`, {
      actionLabel: TODO_ACTIONS.call_now,
      durationMs: TOAST_MS,
      onAction: () => setAction({ type: "debrief", pair: todo, eventId: callEventId }),
    });
  }, [callEventId, showActionToast]);

  // Pusty stan tylko z obu źródeł: z jednym wczytanym okienko mówiło „Nic nie
  // czeka”, zanim przyszło drugie (audyt 13.10.2026). Bez wierszy czekamy, aż
  // drugie odpowie albo padnie; wiersze z pierwszego pokazujemy od razu.
  const cycleSettled = overview !== undefined || cycle.isError;
  const newsSettled = news.data !== undefined || news.isError;
  const state: InterviewsPanelState =
    overview === undefined && news.data === undefined
      ? cycle.isError && news.isError
        ? "error"
        : "loading"
      : view.count === 0 && !(cycleSettled && newsSettled)
        ? "loading"
        : "ready";
  // „Oznacz nowe” przy własnych nowych, które okienko pokazuje — powiadomienie
  // schowane (nieaktualne, po starcie wydarzenia) nie daje przycisku.
  const ownUnread = new Set(notifications.filter((n) => !n.on_behalf_of_name).map((n) => n.id));
  const canMarkNews = [...view.now, ...view.waiting, ...view.news].some((row) =>
    row.unreadIds.some((id) => ownUnread.has(id)),
  );
  const failed =
    state !== "ready"
      ? null
      : cycle.isError && overview === undefined
        ? "tasks"
        : news.isError && news.data === undefined
          ? "news"
          : null;

  return (
    <>
      <Popover open={open} onOpenChange={handleOpenChange}>
        <PopoverTrigger asChild>
          <InterviewsTopbarButton
            count={view.count}
            urgent={view.urgent}
            open={open}
            pill={view.pill ? { name: view.pill.name, minutesLeft: view.pill.minutesLeft } : null}
          />
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="w-[420px] max-w-[calc(100vw-1rem)] overflow-hidden p-0"
        >
          <InterviewsPanel
            state={state}
            view={view}
            failed={failed}
            canMarkNews={canMarkNews}
            markingAll={markRead.isPending}
            actionLabel={(row) => (row.todo && actionFor(row) ? TODO_ACTIONS[row.todo.kind] : null)}
            onOpenRow={openRow}
            onAction={runAction}
            onMarkNewsRead={() => markRead.mutate(undefined)}
            onRetry={() => {
              void cycle.refetch();
              void news.refetch();
            }}
            onOpenSettings={() => {
              setOpen(false);
              router.push(MY_NOTIFICATIONS_SETTINGS_HREF);
            }}
            onOpenCalendar={() => {
              setOpen(false);
              router.push(CALENDAR_HREF);
            }}
          />
        </PopoverContent>
      </Popover>
      {action ? (
        <InterviewActionDialogs
          action={action}
          overview={overview}
          onClose={() => setAction(null)}
        />
      ) : null}
    </>
  );
}
