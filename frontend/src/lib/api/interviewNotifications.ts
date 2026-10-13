import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type NotificationResponse } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";

/** Nieprzeczytane powiadomienia kategorii „Rozmowy” z ostatnich 7 dni. */
export interface InterviewNotificationList {
  items: NotificationResponse[];
}

export const interviewNotificationsApi = {
  list: () => api.get<InterviewNotificationList>("/api/notifications/interviews"),
  /** Bez `ids` — wszystkie własne powiadomienia kategorii. */
  markRead: (ids?: readonly number[]) =>
    api.put("/api/notifications/interviews/read", ids?.length ? { ids } : undefined),
};

/**
 * Klucz pod wspólnym prefiksem `["notifications"]`: gniazdo odświeża go razem
 * z dzwonkiem po każdym powiadomieniu. Własny człon — dzwonek, „Czaty”
 * i „Moje zadania” pytają o inne dane.
 */
export function interviewNotificationsQueryKey(scopeCacheKey: string): readonly unknown[] {
  return ["notifications", scopeCacheKey, "interviews"];
}

export function useInterviewNotifications({ enabled = true }: { enabled?: boolean } = {}) {
  const user = useAuthStore((state) => state.user);
  const scopeCacheKey = `${user?.id ?? "anonymous"}:${user?.authorization_version ?? "none"}`;
  return useQuery({
    queryKey: interviewNotificationsQueryKey(scopeCacheKey),
    queryFn: () => interviewNotificationsApi.list().then((r) => r.data),
    enabled: enabled && Boolean(user),
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
  });
}

export function useMarkInterviewNotificationsRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (ids?: readonly number[]) => interviewNotificationsApi.markRead(ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
