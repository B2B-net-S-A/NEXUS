import { api } from "@/lib/api";

export interface NotificationDeliveryType {
  id: string;
  label: string;
  module: string;
  trigger: string;
  recipient_rule: string;
  email_enabled: boolean;
  effective_enabled: boolean;
  send_not_before: string | null;
  channels: string[];
  sender: string | null;
  editable: boolean;
  provider_kind: string;
  provider_status?: string;
}

export interface NotificationDeliveryOverview {
  enabled: boolean;
  updated_at: string | null;
  updated_by: number | null;
  send_not_before: string | null;
  provider: {
    kind: string;
    sender: string | null;
    configured: boolean;
    observed_status: string;
    last_success_at: string | null;
    last_failure_at: string | null;
    failure_code: string | null;
    cooldown_until: string | null;
  };
  backlog: {
    scope: string;
    pending_retry: number;
    ready_upper_bound: number;
    uncertain: number;
    legacy_suppressed: number;
  };
  types: NotificationDeliveryType[];
  excluded_channels: { id: string; label: string; description: string }[];
}

export interface NotificationDeliveryUpdate {
  enabled: boolean;
  types: { id: string; email_enabled: boolean }[];
}

export const notificationDeliveryApi = {
  get: async () =>
    (await api.get<NotificationDeliveryOverview>("/api/settings/notification-delivery")).data,
  update: async (input: NotificationDeliveryUpdate) =>
    (await api.put<NotificationDeliveryOverview>("/api/settings/notification-delivery", input)).data,
};
