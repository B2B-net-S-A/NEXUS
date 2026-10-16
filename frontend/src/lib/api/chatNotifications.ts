import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";

/**
 * Jedna pozycja okienka „Wiadomości”: czat rekrutacji, czat kandydata albo
 * (od 16.10.2026) wątek notatki — wzmianka lub odpowiedź na Twoją notatkę.
 */
export interface ChatThread {
  kind: "job" | "candidate" | "note";
  entity_id: number;
  title: string;
  /** Czat: klient rekrutacji. Notatka: kto i co („Anna D. oznaczył(a) Cię…”). */
  subtitle: string | null;
  unread_count: number;
  has_mention: boolean;
  last_author_name: string | null;
  last_message: string;
  last_at: string | null;
  /** Pierwsza nieprzeczytana wiadomość, a gdy wszystko przeczytane — ostatnia. */
  link: string;
}

export interface ChatThreadList {
  items: ChatThread[];
  /** Rozmowy z nowymi wiadomościami (ostatnie 30 dni) — licznik na ikonie. */
  unread_threads: number;
}

/** Wątek do zgaszenia: czat po rodzaju i numerze, notatka po linku. */
export type ChatThreadRef = Pick<ChatThread, "kind" | "entity_id" | "link">;

function readBody(thread: ChatThreadRef) {
  return thread.kind === "note"
    ? { kind: "note" as const, link: thread.link }
    : { kind: thread.kind, entity_id: thread.entity_id };
}

export const chatNotificationsApi = {
  list: () =>
    api.get<ChatThreadList>("/api/notifications/chats", {
      params: { include_notes: true },
    }),
  /** Bez wątku — wszystkie czaty i notatki („Oznacz wszystkie”). */
  markRead: async (thread?: ChatThreadRef): Promise<void> => {
    if (thread) {
      await api.put("/api/notifications/chats/read", readBody(thread));
      return;
    }
    await api.put("/api/notifications/chats/read", undefined, {
      params: { include_notes: true },
    });
  },
};

/**
 * Klucz pod wspólnym prefiksem `["notifications"]`: gniazdo odświeża go razem
 * z innymi okienkami po każdej wiadomości czatu (`scheduleChatRefresh`).
 */
export function chatThreadsQueryKey(scopeCacheKey: string): readonly unknown[] {
  return ["notifications", scopeCacheKey, "chats"];
}

export function useChatThreads() {
  const user = useAuthStore((state) => state.user);
  const scopeCacheKey = `${user?.id ?? "anonymous"}:${user?.authorization_version ?? "none"}`;
  return useQuery({
    queryKey: chatThreadsQueryKey(scopeCacheKey),
    queryFn: () => chatNotificationsApi.list().then((r) => r.data),
    enabled: Boolean(user),
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
  });
}

export function useMarkChatThreadsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (thread?: ChatThreadRef) => chatNotificationsApi.markRead(thread),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
