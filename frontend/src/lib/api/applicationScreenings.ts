// „Odrzuceni przez AI” (0404, decyzje Artura 29.09.2026).
//
// Zgłoszenia z linku rekrutacji przegląda AI w tle, zanim osoba trafi do
// „Nowi”. Niepasujący zostają w bazie i na tej liście — z powodem, cytatem
// z CV i „Dodaj mimo to”. Typy są lustrem `backend/app/api/application_screenings.py`.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";

export interface ScreenedOutReason {
  text: string;
  /** Dosłowny cytat z CV sprawdzony przez serwer; `null` = brak cytatu. */
  quote: string | null;
}

export interface ScreenedOutItem {
  id: number;
  candidate_id: number;
  name: string | null;
  lastname: string | null;
  applied_at: string;
  decided_at: string | null;
  /** `failed` = nie udało się ocenić ani dodać automatycznie. */
  status: "done" | "failed" | "pending";
  verdict: "fits" | "unclear" | "not_fit" | null;
  /** `utm_source` zgłoszenia (np. `justjoinit`, `linkedin`). */
  source: string | null;
  must_found: number | null;
  must_total: number | null;
  reasons: ScreenedOutReason[];
}

export interface ScreenedOutResponse {
  job_id: number;
  total: number;
  items: ScreenedOutItem[];
}

export const screenedOutQueryKey = (jobId: number) =>
  ["application-screenings", "screened-out", jobId] as const;

export async function fetchScreenedOut(jobId: number): Promise<ScreenedOutResponse> {
  const { data } = await api.get<ScreenedOutResponse>(`/api/jobs/${jobId}/screened-out`);
  return data;
}

export function useScreenedOut(jobId: number, enabled = true) {
  return useQuery({
    queryKey: screenedOutQueryKey(jobId),
    queryFn: () => fetchScreenedOut(jobId),
    enabled,
    staleTime: 60_000,
  });
}

export function useAddScreenedOut(jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (screeningId: number) => {
      const { data } = await api.post(
        `/api/jobs/${jobId}/screened-out/${screeningId}/add`,
      );
      return data as { job_id: number; candidate_id: number; added: boolean };
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: screenedOutQueryKey(jobId) });
      void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
    },
  });
}

/** „Java 17, Spring: 1 z 3 must-have w CV” — `null`, gdy rekrutacja ich nie ma. */
export function mustSummary(item: Pick<ScreenedOutItem, "must_found" | "must_total">): string | null {
  const total = item.must_total;
  if (total == null || total <= 0) return null;
  return `${item.must_found ?? 0} z ${total} must-have w CV`;
}

const SOURCE_LABEL: Record<string, string> = {
  justjoinit: "JustJoin.IT",
  rocketjobs: "RocketJobs",
  linkedin: "LinkedIn",
};

export function sourceLabel(source: string | null): string | null {
  if (!source) return null;
  return SOURCE_LABEL[source.toLowerCase()] ?? source;
}
