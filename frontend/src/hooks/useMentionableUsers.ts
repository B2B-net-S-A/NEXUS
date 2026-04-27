import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { ChatUserMini } from "@/types/job-chat";

export type MentionScope =
  | { kind: "job"; jobId: number }
  | { kind: "candidate"; candidateId: number }
  | { kind: "global" };

interface UserBrief {
  id: number;
  name: string | null;
  email: string;
  role: string;
}

function toMini(u: UserBrief): ChatUserMini {
  return {
    id: u.id,
    name: u.name ?? u.email,
    email: u.email,
    role: u.role,
  };
}

/**
 * Lista użytkowników do autocomplete @mention. Cache'owana per scope przez
 * react-query (60s staleTime — odświeża się rzadko, członkostwo projektu /
 * lista pracowników nie zmienia się często).
 *
 * Scope:
 *   { kind: "job", jobId }       → members projektu
 *   { kind: "candidate", id }    → members chatu kandydata
 *   { kind: "global" }           → wszyscy aktywni z rolą != `user`
 */
export function useMentionableUsers(scope: MentionScope) {
  const key = scopeKey(scope);
  return useQuery<ChatUserMini[]>({
    queryKey: ["mentionable-users", key],
    queryFn: async () => {
      const params: Record<string, number> = {};
      if (scope.kind === "job") params.job_id = scope.jobId;
      if (scope.kind === "candidate") params.candidate_id = scope.candidateId;
      const resp = await api.get<UserBrief[]>("/api/users/mentionable", {
        params,
      });
      return resp.data.map(toMini);
    },
    staleTime: 60_000,
  });
}

function scopeKey(scope: MentionScope): string {
  if (scope.kind === "job") return `job:${scope.jobId}`;
  if (scope.kind === "candidate") return `candidate:${scope.candidateId}`;
  return "global";
}
