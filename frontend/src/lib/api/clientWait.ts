/**
 * Pas „Czeka na odpowiedź klienta” (S-C2, 08.11.2026). Regułę liczy serwer
 * (`backend/app/services/client_wait.py`); NEXUS nic nie wysyła do klienta,
 * „Przypomnij klientowi” zwraca gotową treść dla Delivery Leada.
 */

import api from "@/lib/api";

export interface ClientWaitPerson {
  candidate_id: number;
  name: string;
  column: "cv_sent" | "client_interview";
  entered_at: string;
  silent_since: string;
  workdays: number;
  needs_action: boolean;
  panel_state: "off" | "unseen" | "viewed" | "interview" | "not_fit";
  panel_label: string;
  reminded_at: string | null;
  closes_on: string | null;
  added_by: string | null;
}

export interface ClientWait {
  after_workdays: number;
  count: number;
  longest_workdays: number;
  panel_enabled: boolean;
  auto_close: boolean;
  auto_close_days: number;
  nearest_close_on: string | null;
  nearest_close_in: number | null;
  people: ClientWaitPerson[];
}

export interface ClientReminder {
  subject: string;
  body: string;
  to_email: string | null;
  panel_url: string | null;
  people: number;
}

export interface ClientWaitSettings {
  auto_close: boolean;
  auto_close_since: string | null;
}

export const clientWaitKey = (jobId: number) => ["client-wait", jobId] as const;
export const CLIENT_WAIT_SETTINGS_KEY = ["client-wait", "settings"] as const;

export async function fetchClientWait(jobId: number): Promise<ClientWait> {
  return (await api.get<ClientWait>(`/api/client-wait/jobs/${jobId}`)).data;
}

/** `candidateIds` puste = wszyscy czekający ponad próg. */
export async function prepareClientReminder(
  jobId: number,
  candidateIds?: number[],
): Promise<ClientReminder> {
  return (
    await api.post<ClientReminder>(`/api/client-wait/jobs/${jobId}/reminder`, {
      ...(candidateIds ? { candidate_ids: candidateIds } : {}),
    })
  ).data;
}

export async function markClientResponded(jobId: number, candidateId: number): Promise<void> {
  await api.post(`/api/client-wait/jobs/${jobId}/candidates/${candidateId}/responded`);
}

export async function fetchClientWaitSettings(): Promise<ClientWaitSettings> {
  return (await api.get<ClientWaitSettings>("/api/client-wait/settings")).data;
}

export async function saveClientWaitSettings(autoClose: boolean): Promise<ClientWaitSettings> {
  return (
    await api.put<ClientWaitSettings>("/api/client-wait/settings", { auto_close: autoClose })
  ).data;
}

/** „1 dzień roboczy”, „2 dni robocze”, „5 dni roboczych”. */
export function workdaysLabel(count: number): string {
  if (count === 1) return "1 dzień roboczy";
  const lastTwo = count % 100;
  if (count % 10 >= 2 && count % 10 <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return `${count} dni robocze`;
  }
  return `${count} dni roboczych`;
}

/** „1 osoba”, „3 osoby”, „5 osób”. */
export function peopleLabel(count: number): string {
  if (count === 1) return "1 osoba";
  const lastTwo = count % 100;
  if (count % 10 >= 2 && count % 10 <= 4 && (lastTwo < 12 || lastTwo > 14)) {
    return `${count} osoby`;
  }
  return `${count} osób`;
}
