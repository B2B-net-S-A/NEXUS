import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";

/** Jedna rozmowa w okienku „Czaty”: czat rekrutacji albo czat kandydata. */
export interface ChatThread {
  kind: "job" | "candidate";
  entity_id: number;
  title: string;
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

export type ChatThreadRef = Pick<ChatThread, "kind" | "entity_id">;

export const chatNotificationsApi = {
  list: () => api.get<ChatThreadList>("/api/notifications/chats"),
  /** Bez rozmowy — wszystkie powiadomienia czatów. */
  markRead: (thread?: ChatThreadRef) =>
    api.put("/api/notifications/chats/read", thread ?? undefined),
};

/**
 * Klucz pod wspólnym prefiksem `["notifications"]`: gniazdo odświeża go razem
 * z dzwonkiem po każdej wiadomości czatu (`scheduleChatRefresh`).
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
