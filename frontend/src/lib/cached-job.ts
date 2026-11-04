"use client";

/**
 * Rekrutacja z cache'u react-query BEZ własnego zapytania.
 *
 * Strona rekrutacji (`page.tsx`: `["job", id]`, `id` ze ścieżki — string)
 * i dok gotowości (`["job", String(jobId)]`) trzymają zlecenie pod jednym
 * kluczem. Komponenty doku (`JobSettingsPanel`, `HiringManagerPicker`,
 * `JobHandoffButton`) czytają z niego pola, których dok im (jeszcze) nie
 * podaje. `enabled: false`: obserwator dostaje dane i zmiany, ale sam nigdy
 * nie wysyła żądania (harness `/preview/*` ma zero zapytań). `queryFn` jest
 * ten sam co w doku, a nie `skipToken` — odświeżenie klucza bierze funkcję
 * z opcji zapytania, a `skipToken` ostatniego obserwatora zepsułby je.
 */
import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";

export function useCachedJob<T = Record<string, unknown>>(
  jobId: number | null | undefined,
): T | undefined {
  const { data } = useQuery<T>({
    queryKey: ["job", String(jobId)],
    queryFn: () => api.get(`/api/jobs/${jobId}`).then((r) => r.data as T),
    enabled: false,
  });
  return jobId == null ? undefined : data;
}
