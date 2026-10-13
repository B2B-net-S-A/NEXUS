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
import { Button } from "@/components/ui/button";
import type {
  InterviewWindow,
  InterviewWindowRow,
  WindowIcon,
  WindowTone,
} from "@/lib/interview-window";
import { notificationTimeAgo } from "@/lib/notification-format";
import { cn } from "@/lib/utils";

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
