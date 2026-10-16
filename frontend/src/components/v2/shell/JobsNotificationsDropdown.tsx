"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Briefcase, CheckCheck, Loader2, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  useJobThreads,
  useMarkJobTopicRead,
  type JobThread,
} from "@/lib/api/jobTopic";
import { formatNotificationText, notificationTimeAgo } from "@/lib/notification-format";
import { MY_NOTIFICATIONS_SETTINGS_HREF } from "@/lib/notification-topics";
import { cn } from "@/lib/utils";
import { useRealtimeStatus } from "@/store/realtime";

function countLabel(n: number): string {
  return n > 99 ? "99+" : String(n);
}

function threadKey(thread: JobThread): string {
  return thread.job_id !== null ? `job:${thread.job_id}` : `link:${thread.link}`;
}

export type JobThreadsPanelState = "loading" | "error" | "ready";

export interface JobThreadsPanelProps {
  state: JobThreadsPanelState;
  threads: JobThread[];
  unreadJobs: number;
  markingAll?: boolean;
  onOpenThread: (thread: JobThread) => void;
  onMarkAllRead: () => void;
  onRetry: () => void;
  onOpenSettings: () => void;
}

/** Treść okienka „Rekrutacje” — bez zapytań, dane w propsach (także w harnessie). */
export function JobThreadsPanel({
  state,
  threads,
  unreadJobs,
  markingAll = false,
  onOpenThread,
  onMarkAllRead,
  onRetry,
  onOpenSettings,
}: JobThreadsPanelProps) {
  return (
    <div className="@container flex max-h-[min(520px,calc(100dvh-6rem))] flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">Rekrutacje</h2>
          <p className="text-xs text-muted-foreground">Twoje rekrutacje z nowościami</p>
        </div>
        <div className="flex items-center gap-1">
          {unreadJobs > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onMarkAllRead}
              disabled={markingAll}
              aria-label="Oznacz wszystkie jako przeczytane"
              className="h-8 gap-1.5 px-2 text-xs"
            >
              <CheckCheck className="h-3.5 w-3.5" aria-hidden />
              Oznacz wszystkie
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
          Wczytuję rekrutacje…
        </div>
      ) : state === "error" ? (
        <div className="px-4 py-8 text-center">
          <p className="text-sm text-foreground">Nie udało się wczytać rekrutacji.</p>
          <Button variant="outline" size="sm" onClick={onRetry} className="mt-3">
            Ponów
          </Button>
        </div>
      ) : threads.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-muted-foreground">
          W Twoich rekrutacjach nic nowego od tygodnia.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
          {threads.map((thread) => (
            <li key={threadKey(thread)}>
              <JobThreadRow thread={thread} onOpen={onOpenThread} />
            </li>
          ))}
        </ul>
      )}

      {state === "ready" && threads.length > 0 ? (
        <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
          Ostatnie 7 dni. Kliknięcie otwiera rekrutację i gasi jej nowości.
        </p>
      ) : null}
    </div>
  );
}

function JobThreadRow({
  thread,
  onOpen,
}: {
  thread: JobThread;
  onOpen: (thread: JobThread) => void;
}) {
  const unread = thread.unread_count > 0;
  return (
    <button
      type="button"
      onClick={() => onOpen(thread)}
      aria-label={`Rekrutacja: ${thread.title}${
        unread ? ` — nowe: ${thread.unread_count}` : ""
      }${unread && thread.has_task ? ", coś dla Ciebie" : ""}`}
      className={cn(
        "flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-hidden",
        unread && "bg-primary/5",
      )}
    >
      <span
        className={cn(
          "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          unread ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground",
        )}
      >
        <Briefcase className="h-4 w-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span
            className={cn(
              "truncate text-sm text-foreground",
              unread ? "font-semibold" : "font-medium",
            )}
          >
            {thread.title}
          </span>
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {notificationTimeAgo(thread.last_at)}
          </span>
        </span>
        {thread.subtitle ? (
          <span className="block truncate text-xs text-muted-foreground">
            {thread.subtitle}
          </span>
        ) : null}
        <span className="mt-1 block truncate text-xs font-medium text-foreground">
          {formatNotificationText(thread.last_title)}
        </span>
        <span className="line-clamp-1 text-xs text-muted-foreground">
          {formatNotificationText(thread.last_message)}
        </span>
      </span>
      {unread ? (
        <span className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-semibold text-primary-foreground tabular-nums">
            {countLabel(thread.unread_count)}
          </span>
          {thread.has_task ? (
            <span className="rounded-full bg-warning/15 px-1.5 text-[11px] font-semibold text-warning">
              dla Ciebie
            </span>
          ) : null}
        </span>
      ) : null}
    </button>
  );
}

export interface JobsTopbarButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  unreadJobs: number;
  open: boolean;
}

/** Ikona „Rekrutacje” w górnym pasku — teczka jak w menu bocznym. */
export function JobsTopbarButton({
  unreadJobs,
  open,
  className,
  ref,
  ...props
}: JobsTopbarButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={
        unreadJobs > 0
          ? `Rekrutacje — z nowościami: ${unreadJobs}`
          : "Rekrutacje"
      }
      title="Rekrutacje — nowości w Twoich rekrutacjach"
      className={cn(
        "relative rounded-lg p-2 transition-colors",
        open
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
        className,
      )}
      {...props}
    >
      <Briefcase className="h-5 w-5" aria-hidden />
      {unreadJobs > 0 ? (
        <span className="absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-xs font-bold text-primary-foreground tabular-nums">
          {countLabel(unreadJobs)}
        </span>
      ) : null}
    </button>
  );
}

/**
 * Okienko „Rekrutacje” w górnym pasku (16.10.2026, w miejscu dzwonka): moje
 * rekrutacje z nowościami — ruchy kandydatów, przydział, termin, Champion,
 * osoby od automatu. Jedna pozycja na rekrutację, jak rozmowa w „Wiadomościach”.
 */
export function JobsNotificationsDropdown() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const setOpenTopic = useRealtimeStatus((s) => s.setOpenTopic);
  const threadsQuery = useJobThreads();
  const markRead = useMarkJobTopicRead();

  const threads = threadsQuery.data?.items ?? [];
  const unreadJobs = threadsQuery.data?.unread_jobs ?? 0;

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    setOpenTopic(next ? "jobs" : null);
  };

  const openThread = (thread: JobThread) => {
    markRead.mutate(
      thread.job_id !== null ? { job_id: thread.job_id } : { link: thread.link },
    );
    onOpenChange(false);
    router.push(thread.link);
  };

  const state: JobThreadsPanelState = threadsQuery.isSuccess
    ? "ready"
    : threadsQuery.isError
      ? "error"
      : "loading";

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <JobsTopbarButton unreadJobs={unreadJobs} open={open} />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 overflow-hidden p-0">
        <JobThreadsPanel
          state={state}
          threads={threads}
          unreadJobs={unreadJobs}
          markingAll={markRead.isPending}
          onOpenThread={openThread}
          onMarkAllRead={() => markRead.mutate(undefined)}
          onRetry={() => void threadsQuery.refetch()}
          onOpenSettings={() => {
            onOpenChange(false);
            router.push(MY_NOTIFICATIONS_SETTINGS_HREF);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
