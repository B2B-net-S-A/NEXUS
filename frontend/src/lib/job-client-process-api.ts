/**
 * Zapytania „Procesu u klienta” (18.11.2026): podpowiedź i czas zmierzony
 * (`GET /api/jobs/client-process`) oraz zapis (`PUT /api/jobs/{id}/client-process`).
 * Reguły: `lib/job-client-process.ts`.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  ClientProcess,
  ClientProcessHints,
  ClientProcessInput,
} from "@/lib/job-client-process";

export function clientProcessHintsKey(clientId: number | null, jobId: number | null) {
  return ["client-process-hints", clientId, jobId] as const;
}

/** Mediany zmieniają się wolno — godzina świeżości wystarcza. */
export function useClientProcessHints(clientId: number | null, jobId: number | null = null) {
  return useQuery({
    queryKey: clientProcessHintsKey(clientId, jobId),
    queryFn: async () => {
      const { data } = await api.get<ClientProcessHints>("/api/jobs/client-process", {
        params: { client_id: clientId, ...(jobId ? { job_id: jobId } : {}) },
      });
      return data;
    },
    enabled: clientId != null && clientId > 0,
    staleTime: 60 * 60 * 1000,
  });
}

export function useSaveClientProcess(jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: ClientProcessInput) => {
      const { data } = await api.put<{ job_id: number; client_process: ClientProcess | null }>(
        `/api/jobs/${jobId}/client-process`,
        input,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
      queryClient.invalidateQueries({ queryKey: ["client-process-hints"] });
    },
  });
}
