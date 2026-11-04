"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCheck, FileSignature, Loader2, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  useContractThreads,
  useMarkContractTopicRead,
  type ContractThread,
} from "@/lib/api/contractTopic";
import { formatNotificationText, notificationTimeAgo } from "@/lib/notification-format";
import { MY_NOTIFICATIONS_SETTINGS_HREF } from "@/lib/notification-topics";
import { cn } from "@/lib/utils";
import { useRealtimeStatus } from "@/store/realtime";

function countLabel(n: number): string {
  return n > 99 ? "99+" : String(n);
}

export type ContractThreadsPanelState = "loading" | "error" | "ready";

export interface ContractThreadsPanelProps {
  state: ContractThreadsPanelState;
  threads: ContractThread[];
  unreadContracts: number;
  markingAll?: boolean;
  onOpenThread: (thread: ContractThread) => void;
  onMarkAllRead: () => void;
  onRetry: () => void;
  onOpenSettings: () => void;
}

/** Treść okienka „Umowy” — bez zapytań, dane w propsach. */
export function ContractThreadsPanel({
  state,
  threads,
  unreadContracts,
  markingAll = false,
  onOpenThread,
  onMarkAllRead,
  onRetry,
  onOpenSettings,
}: ContractThreadsPanelProps) {
  return (
    <div className="@container flex max-h-[min(520px,calc(100dvh-6rem))] flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">Umowy</h2>
          <p className="text-xs text-muted-foreground">Umowy w podpisie i do potwierdzenia</p>
        </div>
        <div className="flex items-center gap-1">
          {unreadContracts > 0 ? (
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
          Wczytuję umowy…
        </div>
      ) : state === "error" ? (
        <div className="px-4 py-8 text-center">
          <p className="text-sm text-foreground">Nie udało się wczytać umów.</p>
          <Button variant="outline" size="sm" onClick={onRetry} className="mt-3">
            Ponów
          </Button>
        </div>
      ) : threads.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-muted-foreground">
          W Twoich umowach nic nowego od dwóch tygodni.
        </p>
      ) : (
        <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
          {threads.map((thread) => (
            <li key={thread.key}>
              <ContractThreadRow thread={thread} onOpen={onOpenThread} />
            </li>
          ))}
        </ul>
      )}

      {state === "ready" && threads.length > 0 ? (
        <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
          Ostatnie 14 dni. Kliknięcie otwiera umowę i gasi jej nowości.
        </p>
      ) : null}
    </div>
  );
}

function ContractThreadRow({
  thread,
  onOpen,
}: {
  thread: ContractThread;
  onOpen: (thread: ContractThread) => void;
}) {
  const unread = thread.unread_count > 0;
  return (
    <button
      type="button"
      onClick={() => onOpen(thread)}
      aria-label={`Umowa: ${thread.title}${unread ? ` — nowe: ${thread.unread_count}` : ""}`}
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
        <FileSignature className="h-4 w-4" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-baseline gap-2">
          <span
            className={cn(
              "truncate text-sm text-foreground",
              unread ? "font-semibold" : "font-medium",
            )}
          >
            {formatNotificationText(thread.title)}
          </span>
          <span className="ml-auto shrink-0 text-xs text-muted-foreground">
            {notificationTimeAgo(thread.last_at)}
          </span>
        </span>
        <span className="mt-1 line-clamp-2 text-xs text-muted-foreground">
          {formatNotificationText(thread.message)}
        </span>
      </span>
      {unread ? (
        <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-primary px-1.5 text-xs font-semibold text-primary-foreground tabular-nums">
          {countLabel(thread.unread_count)}
        </span>
      ) : null}
    </button>
  );
}

export interface ContractsTopbarButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  unreadContracts: number;
  open: boolean;
}

/** Ikona „Umowy” w górnym pasku — dokument z piórem, jak pas podpisu na pulpicie. */
export function ContractsTopbarButton({
  unreadContracts,
  open,
  className,
  ref,
  ...props
}: ContractsTopbarButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={unreadContracts > 0 ? `Umowy — z nowościami: ${unreadContracts}` : "Umowy"}
      title="Umowy — w podpisie i do potwierdzenia"
      className={cn(
        "relative rounded-lg p-2 transition-colors",
        open
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground",
        className,
      )}
      {...props}
    >
      <FileSignature className="h-5 w-5" aria-hidden />
      {unreadContracts > 0 ? (
        <span className="absolute -right-0.5 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-primary px-1 text-xs font-bold text-primary-foreground tabular-nums">
          {countLabel(unreadContracts)}
        </span>
      ) : null}
    </button>
  );
}

/**
 * Okienko „Umowy” w górnym pasku (26.10.2026): umowy w podpisie w NEXUSIE
 * i prośby o potwierdzenie podpisu. Jedna pozycja na umowę; każde nowe
 * zdarzenie podbija liczbę (decyzja Artura). Ikona u wszystkich.
 */
export function ContractsNotificationsDropdown() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const setOpenTopic = useRealtimeStatus((s) => s.setOpenTopic);
  const threadsQuery = useContractThreads();
  const markRead = useMarkContractTopicRead();

  const threads = threadsQuery.data?.items ?? [];
  const unreadContracts = threadsQuery.data?.unread_contracts ?? 0;

  const onOpenChange = (next: boolean) => {
    setOpen(next);
    setOpenTopic(next ? "contracts" : null);
  };

  const openThread = (thread: ContractThread) => {
    if (thread.unread_ids.length > 0) {
      markRead.mutate({ ids: thread.unread_ids });
    }
    onOpenChange(false);
    router.push(thread.link);
  };

  const state: ContractThreadsPanelState = threadsQuery.isSuccess
    ? "ready"
    : threadsQuery.isError
      ? "error"
      : "loading";

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <ContractsTopbarButton unreadContracts={unreadContracts} open={open} />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 overflow-hidden p-0">
        <ContractThreadsPanel
          state={state}
          threads={threads}
          unreadContracts={unreadContracts}
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
