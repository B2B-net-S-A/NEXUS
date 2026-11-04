// Ustawienia → Powiadomienia → „Kto co dostaje”: która ROLA dostaje którą
// grupę powiadomień w dzwonku. Kategorie, grupy i role zna wyłącznie backend
// (`services/notification_role_view.py`) — front niczego tu nie powtarza.
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { refusalCode } from "@/lib/help/refusal-tracker";
import type {
  NotificationRoleChange,
  NotificationRolesView,
} from "@/lib/notification-role-matrix";

export const notificationRolesQueryKey = ["settings-notification-roles"] as const;

export const notificationRolesApi = {
  get: () =>
    api
      .get<NotificationRolesView>("/api/settings/notification-roles")
      .then((r) => r.data),
  update: (revision: number, changes: NotificationRoleChange[]) =>
    api
      .put<NotificationRolesView>("/api/settings/notification-roles", {
        revision,
        changes,
      })
      .then((r) => r.data),
};

/** 409 „ktoś zapisał w międzyczasie” — jedyna odmowa, po której wczytujemy
 *  tabelę od nowa i porzucamy szkic. */
export function isStaleNotificationRolesError(error: unknown): boolean {
  const response = (
    error as { response?: { status?: unknown; data?: unknown } } | null
  )?.response;
  return (
    typeof response?.status === "number" &&
    refusalCode(response.status, response.data) === "stale_notification_roles"
  );
}

export function useNotificationRoles(enabled: boolean) {
  return useQuery({
    queryKey: notificationRolesQueryKey,
    queryFn: notificationRolesApi.get,
    enabled,
  });
}
