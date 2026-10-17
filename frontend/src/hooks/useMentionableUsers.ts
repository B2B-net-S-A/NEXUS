import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useAbsences, useLeaveModuleOpen, type PersonAbsence } from "@/lib/api/hr-leave";
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

interface UseMentionableUsersOptions {
  /**
   * Pokaż też nieaktywnych userów (np. 131 importowanych z Traffit jako
   * disabled accounts w Faza A). Domyślnie false — pokazuje tylko aktywnych.
   * Włączane gdy renderujemy historyczne notatki/komentarze i chcemy mention'ować
   * autora którego konto wygasło.
   */
  includeInactive?: boolean;
  /**
   * Dociągnij dzisiejsze nieobecności osób z listy (plakietka w liście „@”
   * i podpowiedź zastępcy) — jedno zapytanie na całą listę. Tylko przy
   * otwartym module urlopów; bez niego albo przy awarii `absences` jest
   * puste, a wzmianki działają jak dotąd.
   */
  withAbsences?: boolean;
}

const NO_ABSENCES: ReadonlyMap<number, PersonAbsence> = new Map();

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
export function useMentionableUsers(
  scope: MentionScope,
  opts: UseMentionableUsersOptions = {},
) {
  const key = scopeKey(scope);
  const includeInactive = Boolean(opts.includeInactive);
  const withAbsences = Boolean(opts.withAbsences);
  const query = useQuery<ChatUserMini[]>({
    queryKey: ["mentionable-users", key, includeInactive],
    queryFn: async () => {
      const params: Record<string, number | string> = {};
      if (scope.kind === "job") params.job_id = scope.jobId;
      if (scope.kind === "candidate") params.candidate_id = scope.candidateId;
      if (includeInactive) params.include_inactive = "true";
      const resp = await api.get<UserBrief[]>("/api/users/mentionable", {
        params,
      });
      return resp.data.map(toMini);
    },
    staleTime: 60_000,
  });
  const leaveOpen = useLeaveModuleOpen(withAbsences);
  const absences = useAbsences(
    withAbsences ? (query.data ?? []).map((user) => user.id) : [],
    { enabled: withAbsences && leaveOpen },
  );
  return {
    ...query,
    absences: absences.isSuccess ? absences.byUser : NO_ABSENCES,
  };
}

function scopeKey(scope: MentionScope): string {
  if (scope.kind === "job") return `job:${scope.jobId}`;
  if (scope.kind === "candidate") return `candidate:${scope.candidateId}`;
  return "global";
}
