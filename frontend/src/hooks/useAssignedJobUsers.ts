import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { ChatUserMini } from "@/types/job-chat";

/**
 * Osoby przypisane do rekrutacji — kogo oznacza `@wszyscy` (13.11.2026).
 * Serwer liczy tę samą listę przy zapisie wiadomości albo notatki
 * (`list_job_assigned_ids`), tu służy tylko do podpowiedzi i podglądu,
 * kto dostanie wzmiankę. `null` = pole poza rekrutacją, bez zapytania.
 */
export function useAssignedJobUsers(jobId: number | null) {
  return useQuery<ChatUserMini[]>({
    queryKey: ["job-assigned-users", jobId],
    queryFn: async () =>
      (
        await api.get<ChatUserMini[]>(`/api/jobs/${jobId}/chat/members`, {
          params: { assigned: true },
        })
      ).data,
    enabled: jobId != null,
    staleTime: 60_000,
  });
}
