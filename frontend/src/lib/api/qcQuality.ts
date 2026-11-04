// „Jakość QC” (D6, 13.10.2026) — trafność sprawdzeń QC CV z pominięć „To
// nieprawda” i ich stan. Lustro `GET/PATCH /api/settings/ai/qc-quality`
// (backend: `api/ai_settings.py`, `services/qc_quality.py`). Tylko admin.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";

export type QcCheckState = "active" | "info" | "off";

export interface QcQualityCheck {
  key: string;
  label: string;
  blocking: boolean;
  /** Różne pozycje (para × klucz) pokazane w oknie — łącznie z pominiętymi. */
  shown: number;
  /** Pominięte jako „QC się myli” (trzy pierwsze powody), tylko trwające. */
  dismissed_wrong: number;
  /** 0–1; `null`, gdy nic nie pokazano. */
  precision: number | null;
  /** Kod powodu → liczba trwających pominięć. */
  reasons: Record<string, number>;
  /** Stan, z którym QC liczy się teraz. */
  state: QcCheckState;
  /** Decyzja automatu (`info` = wyciszone przez trafność). */
  auto: "info" | null;
  /** Ręczny stan administratora — wygrywa z automatem; `null` = automat. */
  manual: QcCheckState | null;
}

export interface QcQualityDismissal {
  id: number;
  check_key: string;
  check_label: string;
  label: string;
  reason: string;
  reason_label: string;
  note: string | null;
  by_name: string | null;
  at: string;
  restored: boolean;
  job_id: number;
  candidate_id: number;
}

export interface QcQualityReport {
  window_days: number;
  auto_min_shown: number;
  /** Próg automatu dla uwag (0–1). */
  auto_info_below: number;
  /** Próg powiadomienia adminów dla blokad (0–1). */
  alert_blocking_below: number;
  checks: QcQualityCheck[];
  recent: QcQualityDismissal[];
}

export const qcQualityQueryKey = ["qc-quality"] as const;

export function useQcQuality() {
  return useQuery<QcQualityReport>({
    queryKey: qcQualityQueryKey,
    queryFn: () => api.get<QcQualityReport>("/api/settings/ai/qc-quality").then((r) => r.data),
  });
}

/** Ręczny stan uwagi (`null` = wróć do automatu); blokad serwer nie przyjmuje (422). */
export function useSetQcCheckState() {
  const queryClient = useQueryClient();
  return useMutation<QcQualityReport, unknown, { key: string; state: QcCheckState | null }>({
    mutationFn: ({ key, state }) =>
      api
        .patch<QcQualityReport>(`/api/settings/ai/qc-quality/${encodeURIComponent(key)}`, { state })
        .then((r) => r.data),
    onSuccess: (report) => queryClient.setQueryData(qcQualityQueryKey, report),
  });
}
