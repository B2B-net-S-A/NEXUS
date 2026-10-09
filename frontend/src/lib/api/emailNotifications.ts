// „Maile do Ciebie” (0427): które maile dostaje to konto i własne wyłączniki
// (`GET /api/users/me/email-notifications`, `PUT …/{kind}`). Nazwy maili,
// stan i zdanie wyjaśnienia liczy backend
// (`services/notification_email_prefs.py`) — front niczego tu nie powtarza.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { USER_PREFERENCES_QUERY_KEY } from "@/lib/api/userPreferences";

export type MyEmailState =
  | "on"
  | "self_off"
  | "company_off"
  | "bell_muted"
  | "role_muted";

export interface MyEmailNotification {
  id: string;
  label: string;
  /** Kiedy mail wychodzi. */
  description: string;
  /** Administrator ma ten mail włączony dla firmy. */
  company_enabled: boolean;
  /** Własny wyłącznik konta — zapamiętany także przy firmowym wyłączeniu. */
  self_enabled: boolean;
  /** Wynik końcowy: mail naprawdę przychodzi. */
  receiving: boolean;
  state: MyEmailState;
  /** Gotowe zdanie, dlaczego mail nie przychodzi; `null` gdy przychodzi. */
  note: string | null;
}

export interface MyEmailNotifications {
  /** `false` = wysyłka maili z NEXUSA nie jest teraz skonfigurowana. */
  channel_ready: boolean;
  items: MyEmailNotification[];
  not_applicable: { id: string; label: string }[];
  always_on: { id: string; label: string; description: string }[];
}

export const MY_EMAIL_NOTIFICATIONS_QUERY_KEY = ["my-email-notifications"] as const;

export const myEmailNotificationsApi = {
  get: () =>
    api
      .get<MyEmailNotifications>("/api/users/me/email-notifications")
      .then((r) => r.data),
  setEnabled: (kind: string, enabled: boolean) =>
    api
      .put<MyEmailNotifications>(
        `/api/users/me/email-notifications/${encodeURIComponent(kind)}`,
        { enabled },
      )
      .then((r) => r.data),
};

export function useMyEmailNotifications() {
  return useQuery({
    queryKey: MY_EMAIL_NOTIFICATIONS_QUERY_KEY,
    queryFn: myEmailNotificationsApi.get,
    staleTime: 60_000,
  });
}

export interface SetMyEmailVars {
  kind: string;
  enabled: boolean;
}

export function useSetMyEmailNotification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, enabled }: SetMyEmailVars) =>
      myEmailNotificationsApi.setEnabled(kind, enabled),
    onSuccess: (data) => {
      queryClient.setQueryData(MY_EMAIL_NOTIFICATIONS_QUERY_KEY, data);
      // Poranny skrót ma lustro w preferencjach konta (ekran Coaching KPI).
      queryClient.invalidateQueries({ queryKey: USER_PREFERENCES_QUERY_KEY });
    },
  });
}
