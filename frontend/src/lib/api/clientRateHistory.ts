// Stawka do klienta po wysyłce CV (20.10.2026, wariant A).
//
// Backend: `services/client_rate_correction.py`, trasa
// `GET /api/candidates/{id}/recruitments/{job_id}/client-rate/history`.
// Za ile CV poszło do klienta, zmiany po wysyłce (z powodem) i blokada po
// zamówieniu — wtedy stawkę zmienia się w zamówieniu, nie w rekrutacji.
// Rekruter dostaje 403 (nie widzi stawki do klienta), więc hook pyta tylko
// za `enabled` liczonym przez wołającego z `canViewClientRate`.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { RateUnit } from "@/lib/api";

export type ClientRateChangeReason = "client_negotiated" | "send_mistake" | "other";

export interface ClientRateAmount {
  value: number;
  unit: RateUnit | null;
  currency: string;
}

export interface ClientRateChange {
  at: string;
  by_name: string | null;
  old: ClientRateAmount | null;
  new: ClientRateAmount | null;
  old_label: string;
  new_label: string;
  reason: ClientRateChangeReason | null;
  reason_label: string | null;
  note: string | null;
}

export interface ClientRateOrderLock {
  order_id: number;
  contract_id: number;
  title: string;
  rate_client: number | null;
  rate_unit: RateUnit | null;
  currency: string;
}

export interface ClientRateHistory {
  current: ClientRateAmount | null;
  current_label: string | null;
  sent: {
    at: string;
    by_name: string | null;
    rate: ClientRateAmount | null;
    label: string | null;
  } | null;
  changes: ClientRateChange[];
  order_lock: ClientRateOrderLock | null;
  can_write: boolean;
  reasons: { value: ClientRateChangeReason; label: string }[];
}

export const clientRateHistoryQueryKey = (candidateId: number, jobId: number) =>
  ["client-rate-history", candidateId, jobId] as const;

export async function fetchClientRateHistory(
  candidateId: number,
  jobId: number,
): Promise<ClientRateHistory> {
  const { data } = await api.get<ClientRateHistory>(
    `/api/candidates/${candidateId}/recruitments/${jobId}/client-rate/history`,
  );
  return data;
}

export function useClientRateHistory(
  candidateId: number | null,
  jobId: number | null,
  enabled: boolean,
) {
  return useQuery({
    queryKey: clientRateHistoryQueryKey(candidateId ?? 0, jobId ?? 0),
    enabled: enabled && candidateId != null && jobId != null,
    queryFn: () => fetchClientRateHistory(candidateId as number, jobId as number),
    staleTime: 15_000,
  });
}

/** „17.10” — dzień i miesiąc w kalendarzu firmy. */
export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Europe/Warsaw",
  });
}

/** Linia pod kwotą w panelu: za ile poszło CV i ostatnia zmiana. */
export function sentLine(history: ClientRateHistory): string | null {
  const sent = history.sent;
  if (!sent?.label) return null;
  const last = history.changes[0];
  if (!last) return `CV poszło za ${sent.label} (${shortDate(sent.at)})`;
  const who = last.by_name ? ` przez ${last.by_name}` : "";
  const why = last.reason_label ? ` · ${last.reason_label.toLowerCase()}` : "";
  return `CV poszło za ${sent.label} · zmienione ${shortDate(last.at)}${who}${why}`;
}
