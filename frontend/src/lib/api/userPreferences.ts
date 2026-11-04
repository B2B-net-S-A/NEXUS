// Własne przełączniki konta (`GET`/`PATCH /api/users/me/preferences`):
// coaching KPI i poranny skrót mailem. Jeden klucz zapytania dla obu ekranów
// (Coaching KPI, Powiadomienia → „Moje”), żeby zapis w jednym odświeżał drugi.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface UserPreferences {
  kpi_coach_enabled: boolean;
  /** Poranny skrót „Twój dzień w NEXUSIE” — wyłącznik tylko dla tego konta. */
  daily_digest_email_enabled: boolean;
  /** `false` = rola tego konta nigdy nie dostaje skrótu; przełącznika nie pokazujemy. */
  daily_digest_email_available: boolean;
}

export type UserPreferencesUpdate = Partial<
  Pick<UserPreferences, "kpi_coach_enabled" | "daily_digest_email_enabled">
>;

export const USER_PREFERENCES_QUERY_KEY = ["user-preferences", "me"] as const;

export const userPreferencesApi = {
  get: () =>
    api.get<UserPreferences>("/api/users/me/preferences").then((r) => r.data),
  update: (input: UserPreferencesUpdate) =>
    api
      .patch<UserPreferences>("/api/users/me/preferences", input)
      .then((r) => r.data),
};

export function useUserPreferences() {
  return useQuery({
    queryKey: USER_PREFERENCES_QUERY_KEY,
    queryFn: userPreferencesApi.get,
    staleTime: 60_000,
  });
}

export function useUpdateUserPreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: userPreferencesApi.update,
    onSuccess: (data) => {
      queryClient.setQueryData(USER_PREFERENCES_QUERY_KEY, data);
    },
  });
}
