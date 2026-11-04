/**
 * Dane do pytania „Ile dni w biurze kandydat akceptuje?” w oknie odrzucenia
 * (14.10.2026): tryb pracy rekrutacji i tryb pracy z profilu jednej osoby.
 *
 * Oba zapytania dzielą klucze z ekranami, które już je trzymają w cache'u —
 * strona rekrutacji (`["job", id]`) i dok osoby / profil
 * (`candidateQueryKeys.detail`) — więc okno zwykle nie wysyła nic nowego.
 * Brak danych nie blokuje odrzucenia: bez rekrutacji pytanie daje 0–4 dni,
 * bez profilu znika tylko linia „Teraz na profilu”.
 */

import { useQuery } from "@tanstack/react-query";

import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import type {
  RejectionWorkModeJob,
  RejectionWorkModeProfile,
} from "@/components/v2/modals/RejectionWorkModeField";
import type { RejectionRateProfile } from "@/components/v2/modals/RejectionRateField";
import api, { candidatesApi } from "@/lib/api";
import { toAmount } from "@/lib/candidate-rate";
import { profileWorkMode } from "@/lib/work-mode";

interface JobWorkModeFields {
  remote_policy?: string | null;
  onsite_days_per_week?: number | null;
}

/** Tryb pracy rekrutacji z odpowiedzi `GET /api/jobs/{id}`. */
export function rejectionWorkModeJob(
  job: JobWorkModeFields | null | undefined,
): RejectionWorkModeJob | null {
  if (!job) return null;
  return {
    remotePolicy: job.remote_policy ?? null,
    onsiteDaysPerWeek:
      typeof job.onsite_days_per_week === "number" ? job.onsite_days_per_week : null,
  };
}

export function useRejectionWorkModeJob(
  jobId: number | null | undefined,
  enabled = true,
): RejectionWorkModeJob | null {
  const query = useQuery<JobWorkModeFields>({
    queryKey: ["job", String(jobId)],
    queryFn: () => api.get(`/api/jobs/${jobId}`).then((r) => r.data),
    enabled: enabled && jobId != null,
    staleTime: 60_000,
    retry: false,
  });
  return rejectionWorkModeJob(query.data);
}

/** `undefined`, dopóki profil nie jest wczytany (albo osób jest kilka). */
export function useRejectionProfileWorkMode(
  candidateId: number | null | undefined,
  enabled = true,
): RejectionWorkModeProfile | undefined {
  const query = useQuery<{ preferences?: unknown; max_onsite_days_per_week?: number | null }>({
    queryKey: candidateQueryKeys.detail(candidateId ?? 0),
    queryFn: () => candidatesApi.get(candidateId as number).then((r) => r.data),
    enabled: enabled && candidateId != null,
    staleTime: 60_000,
  });
  if (!query.data) return undefined;
  return profileWorkMode(query.data.preferences, query.data.max_onsite_days_per_week);
}

/** „Stawka od” jednej osoby do pytania „Ile teraz chce?” (26.10.2026) — ten
 *  sam wpis cache'u co tryb pracy wyżej. */
export function useRejectionProfileRate(
  candidateId: number | null | undefined,
  enabled = true,
): RejectionRateProfile | undefined {
  const query = useQuery<{ rate_from_hourly?: string | number | null; rate_from_at?: string | null }>({
    queryKey: candidateQueryKeys.detail(candidateId ?? 0),
    queryFn: () => candidatesApi.get(candidateId as number).then((r) => r.data),
    enabled: enabled && candidateId != null,
    staleTime: 60_000,
  });
  if (!query.data) return undefined;
  return {
    rateFromHourly: toAmount(query.data.rate_from_hourly),
    rateFromAt: query.data.rate_from_at ?? null,
  };
}
