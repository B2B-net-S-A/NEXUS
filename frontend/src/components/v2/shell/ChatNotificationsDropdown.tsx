"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AtSign,
  Briefcase,
  CheckCheck,
  Loader2,
  MessageSquare,
  Settings2,
  User,
} from "lucide-react";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { isChatOnScreen } from "@/lib/active-chat";
import {
  useChatThreads,
  useMarkChatThreadsRead,
  type ChatThread,
} from "@/lib/api/chatNotifications";
import { chatNotifyMessage, shouldShowChatToast } from "@/lib/chat-notify";
import { formatNotificationText, notificationTimeAgo } from "@/lib/notification-format";
import { cn } from "@/lib/utils";
import { CHAT_NOTIFY_EVENT, type ChatNotifyEvent } from "@/types/job-chat";

const SETTINGS_HREF = "/settings?item=my-notifications";
const CHAT_TOAST_MS = 8_000;

function countLabel(n: number): string {
  return n > 99 ? "99+" : String(n);
}

function threadKindLabel(kind: ChatThread["kind"]): string {
  return kind === "candidate" ? "Czat kandydata" : "Czat rekrutacji";
}

export type ChatThreadsPanelState = "loading" | "error" | "ready";

export interface ChatThreadsPanelProps {
  state: ChatThreadsPanelState;
  threads: ChatThread[];
  unreadThreads: number;
  markingAll?: boolean;
  onOpenThread: (thread: ChatThread) => void;
  onMarkAllRead: () => void;
  onRetry: () => void;
  onOpenSettings: () => void;
}

/** Treść okienka „Czaty” — bez zapytań, dane w propsach (także w harnessie). */
export function ChatThreadsPanel({
  state,
  threads,
  unreadThreads,
  markingAll = false,
  onOpenThread,
  onMarkAllRead,
  onRetry,
  onOpenSettings,
}: ChatThreadsPanelProps) {
  return (
    <div className="@container flex max-h-[min(520px,calc(100dvh-6rem))] flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold text-foreground">Czaty</h2>
        <div className="flex items-center gap-1">
          {unreadThreads > 0 ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={onMarkAllRead}
              disabled={markingAll}
              aria-label="Oznacz wszystkie jako przeczytane"
              className="h-8 gap-1.5 px-2 text-xs"
            >
              <CheckCheck className="h-3.5 w-3.5" aria-hidden />
              {/* W węższym okienku (telefon) pełne zdanie wypychało ikonę
                  ustawień poza krawędź — decyduje szerokość okienka, nie ekranu. */}
              <span className="@[376px]:hidden">Oznacz wszystkie</span>
              <span className="hidden @[376px]:inline">
                Oznacz wszystkie jako przeczytane
              </span>
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
        <div className="px-4 py-8 text-center">
          <p className="text-sm text-foreground">Nie udało się wczytać rozmów.</p>
          <Button variant="outline" size="sm" onClick={onRetry} className="mt-3">
            Ponów
          </Button>
        </div>
      ) : threads.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-muted-foreground">
          Nie masz wiadomości w czatach z ostatnich 30 dni.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
          {threads.map((thread) => (
            <li key={`${thread.kind}:${thread.entity_id}`}>
              <ChatThreadRow thread={thread} onOpen={onOpenThread} />
            </li>
          ))}
        </ul>
      )}

      {state === "ready" && threads.length > 0 ? (
        <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
          Rozmowy z ostatnich 30 dni. Kliknięcie otwiera pierwszą nieprzeczytaną
          wiadomość.
        </p>
      ) : null}
    </div>
  );
}

function ChatThreadRow({
  thread,
  onOpen,
}: {
  thread: ChatThread;
  onOpen: (thread: ChatThread) => void;
}) {
  const unread = thread.unread_count > 0;
  const KindIcon = thread.kind === "candidate" ? User : Briefcase;
  const message = formatNotificationText(thread.last_message);
  return (
    <button
      type="button"
      onClick={() => onOpen(thread)}
      aria-label={`${threadKindLabel(thread.kind)}: ${thread.title}${
        unread ? ` — nowe wiadomości: ${thread.unread_count}` : ""
      }${unread && thread.has_mention ? ", oznaczono Cię" : ""}`}
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
        <KindIcon className="h-4 w-4" aria-hidden />
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
        <span className="block truncate text-xs text-muted-foreground">
          {thread.subtitle
            ? `${threadKindLabel(thread.kind)} · ${thread.subtitle}`
            : threadKindLabel(thread.kind)}
        </span>
        <span className="mt-1 line-clamp-2 text-xs text-muted-foreground">
          {thread.last_author_name ? (
            <span className="font-medium text-foreground">
              {thread.last_author_name}:{" "}
            </span>
          ) : null}
          {message}
        </span>
      </span>
      {unread ? (
        <span className="flex shrink-0 flex-col items-end gap-1 pt-0.5">
          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-semibold text-primary-foreground tabular-nums">
            {countLabel(thread.unread_count)}
          </span>
          {thread.has_mention ? (
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-destructive/10 text-destructive">
              <AtSign className="h-3 w-3" aria-hidden />
              <span className="sr-only">wzmianka</span>
            </span>
          ) : null}
        </span>
      ) : null}
    </button>
  );
}

export interface ChatTopbarButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  unreadThreads: number;
  hasMention: boolean;
  open: boolean;
}

/** Ikona „Czaty” w górnym pasku — wygląd jak dzwonek obok. */
export function ChatTopbarButton({
  unreadThreads,
  hasMention,
  open,
  className,
  ref,
  ...props
}: ChatTopbarButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={
        unreadThreads > 0
          ? `Czaty — rozmowy z nowymi wiadomościami: ${unreadThreads}`
          : "Czaty"
      }
      className={cn(
        "relative rounded-lg p-2 transition-colors",
        open
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
        className,
      )}
      {...props}
    >
      <MessageSquare className="h-5 w-5" aria-hidden />
      {unreadThreads > 0 ? (
        <span
          className={cn(
            "absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-xs font-bold tabular-nums",
            hasMention
              ? "bg-destructive text-white"
              : "bg-primary text-primary-foreground",
          )}
        >
          {countLabel(unreadThreads)}
        </span>
      ) : null}
    </button>
  );
}

/**
 * Okienko „Czaty” w górnym pasku (09.10.2026): powiadomienia czatów rekrutacji
 * i kandydatów, jedna pozycja na rozmowę. Dzwonek ich już nie pokazuje.
 * Nowa wiadomość daje dymek z „Otwórz”, chyba że ten czat jest na ekranie.
 */
export function ChatNotificationsDropdown() {
  const router = useRouter();
  const { showActionToast } = useToast();
  const [open, setOpen] = useState(false);
  const threadsQuery = useChatThreads();
  const markRead = useMarkChatThreadsRead();

  const threads = threadsQuery.data?.items ?? [];
  const unreadThreads = threadsQuery.data?.unread_threads ?? 0;
  const hasMention = threads.some((t) => t.unread_count > 0 && t.has_mention);

  const openThread = (thread: Pick<ChatThread, "kind" | "entity_id" | "link">) => {
    // Czat tylko do odczytu nie gasi powiadomień sam — gasimy je tutaj.
    markRead.mutate({ kind: thread.kind, entity_id: thread.entity_id });
    setOpen(false);
    router.push(thread.link);
  };
  const openThreadRef = useRef(openThread);
  openThreadRef.current = openThread;

  const lastToastRef = useRef<Map<string, number>>(new Map());
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<ChatNotifyEvent>).detail;
      if (!detail || !detail.link) return;
      if (isChatOnScreen(detail.kind, detail.entity_id)) return;
      if (!shouldShowChatToast(detail, lastToastRef.current, Date.now())) return;
      showActionToast(chatNotifyMessage(detail), {
        actionLabel: "Otwórz",
        durationMs: CHAT_TOAST_MS,
        onAction: () => openThreadRef.current(detail),
      });
    };
    window.addEventListener(CHAT_NOTIFY_EVENT, handler);
    return () => window.removeEventListener(CHAT_NOTIFY_EVENT, handler);
  }, [showActionToast]);

  const state: ChatThreadsPanelState = threadsQuery.isSuccess
    ? "ready"
    : threadsQuery.isError
      ? "error"
      : "loading";

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <ChatTopbarButton
          unreadThreads={unreadThreads}
          hasMention={hasMention}
          open={open}
        />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 overflow-hidden p-0">
        <ChatThreadsPanel
          state={state}
          threads={threads}
          unreadThreads={unreadThreads}
          markingAll={markRead.isPending}
          onOpenThread={openThread}
          onMarkAllRead={() => markRead.mutate(undefined)}
          onRetry={() => void threadsQuery.refetch()}
          onOpenSettings={() => {
            setOpen(false);
            router.push(SETTINGS_HREF);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
