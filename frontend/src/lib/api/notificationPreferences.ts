// Własne ustawienia powiadomień (0349): które KATEGORIE trafiają do dzwonka.
// Kategorie, ich nazwy i to, które są obowiązkowe, zna wyłącznie backend
// (`services/notification_categories.py`) — front niczego tu nie powtarza.
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { api } from "@/lib/api";
import { MY_EMAIL_NOTIFICATIONS_QUERY_KEY } from "@/lib/api/emailNotifications";

export interface NotificationCategoryPreference {
  key: string;
  label: string;
  description: string;
  mandatory: boolean;
  muted: boolean;
  /** Administrator wyłączył CAŁĄ kategorię wszystkim rolom tego konta —
   *  własny przełącznik jej nie włączy (Ustawienia → Powiadomienia →
   *  „Kto co dostaje”). */
  role_muted?: boolean;
  /** Ile powiadomień tej kategorii przyszło w ostatnich 30 dniach. */
  received_30d: number;
}

export interface NotificationPreferences {
  categories: NotificationCategoryPreference[];
}

export const notificationPreferencesQueryKey = ["notification-preferences"] as const;

export const notificationPreferencesApi = {
  get: () =>
    api
      .get<NotificationPreferences>("/api/notifications/preferences")
      .then((r) => r.data),
  setMuted: (category: string, muted: boolean) =>
    api
      .put<NotificationPreferences>(
        `/api/notifications/preferences/${encodeURIComponent(category)}`,
        { muted },
      )
      .then((r) => r.data),
};

export function useNotificationPreferences() {
  return useQuery({
    queryKey: notificationPreferencesQueryKey,
    queryFn: notificationPreferencesApi.get,
    staleTime: 60_000,
  });
}

export interface SetCategoryMutedVars {
  category: string;
  muted: boolean;
}

/** Zmiana jednej kategorii. Odświeża też dzwonek i jego licznik — wyciszona
 *  kategoria znika z listy, a po ponownym włączeniu powiadomienia z czasu
 *  wyciszenia serwer oznacza jako przeczytane. */
export function useSetNotificationCategoryMuted() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ category, muted }: SetCategoryMutedVars) =>
      notificationPreferencesApi.setMuted(category, muted),
    onSuccess: (data) => {
      queryClient.setQueryData(notificationPreferencesQueryKey, data);
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      // Mail idący za wyciszoną kategorią też przestaje przychodzić —
      // „Maile do Ciebie” mówi to przy wierszu.
      queryClient.invalidateQueries({ queryKey: MY_EMAIL_NOTIFICATIONS_QUERY_KEY });
    },
  });
}
