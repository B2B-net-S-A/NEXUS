// Powiadomienia Delivery Leada — sekcja w dashboardzie, z logiem obsłużenia.
//
// Osobno od dzwonka (`notificationsApi`), bo to inny kontrakt: tamten zna
// wyłącznie „przeczytane", ten prowadzi trwały ślad kto/kiedy sprawę załatwił
// i ile to trwało. Czas reakcji przychodzi z SERWERA — front go nie wylicza,
// żeby liczba w tabeli i liczba w eksporcie XLSX nie mogły się rozjechać.

import { api } from "@/lib/api";

export type DlAlertStatus = "new" | "handled";

export type DlAlertType =
  | "cost_order_exhausted"
  | "draft_consultant_unassigned"
  | "md_budget_low"
  | "missing_revenue_rate"
  | "md_consultant_ended";

export interface DlAlertRead {
  id: number;
  alert_type: DlAlertType;
  alert_type_label: string;
  status: DlAlertStatus;
  status_label: string;

  client_id: number;
  client_name: string;
  order_group_id: number | null;
  order_id: number | null;

  title: string;
  message: string;
  link: string | null;

  recipient_user_id: number;
  recipient_name: string;

  created_at: string;
  handled_at: string | null;
  handled_by_user_id: number | null;
  handled_by_name: string | null;
  reaction_seconds: number | null;
  reaction_label: string;
}

export interface DlAlertListResponse {
  alerts: DlAlertRead[];
  total_new: number;
  total_handled: number;
}

export const dlAlertsApi = {
  list: (status: DlAlertStatus, limit = 50) =>
    api.get<DlAlertListResponse>("/api/dl-alerts", { params: { status, limit } }),

  markHandled: (alertId: number) =>
    api.post<DlAlertRead>(`/api/dl-alerts/${alertId}/handled`, {}),
};

/** URL eksportu. Pobranie idzie przez `fetch` z Bearerem i blobem — axios
 *  z `responseType:"blob"` bywa zawodny cross-origin (ta sama decyzja co
 *  w `lib/authenticated-files.ts` i eksporcie kontraktów). */
export function dlAlertsExportUrl(scope: "mine" | "all"): string {
  const base = process.env.NEXT_PUBLIC_API_URL || "";
  return `${base}/api/dl-alerts/export?scope=${scope}`;
}
