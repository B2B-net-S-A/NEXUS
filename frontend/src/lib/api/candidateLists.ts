// Listy kandydatów w „Moich ludziach” (prośba Olafa, decyzja Artura 25.10.2026).
//
// Lista to osobista pula talentów (`talent_pools.is_personal`, 0137) z
// widocznością „Tylko ja” / „Widzi zespół” (`team_visible`, 0520). Typy są
// lustrem `backend/app/api/talent_pools.py`. Kto widzi cudzą listę, rozstrzyga
// serwer: prywatna lista innej osoby po prostu nie przychodzi.
//
// Klucze zapytań stoją pod prefiksem `["talent-pools"]`, więc dotychczasowe
// unieważnienia (/talents, okno „Dodaj do puli”, profil) odświeżają też listy.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface TalentPoolOut {
  id: number;
  name: string;
  description: string | null;
  candidate_count: number;
  created_at: string;
  is_personal: boolean;
  owner_id: number | null;
  owner_name: string | null;
  is_marketplace?: boolean;
  team_visible: boolean;
}

export interface ListMember {
  id: number;
  name: string;
  lastname: string;
  location: string | null;
  skills: unknown[] | null;
  added_at: string;
}

export interface ListMembersResponse {
  pool: {
    id: number;
    name: string;
    candidate_count: number;
    is_personal: boolean;
    owner_id: number | null;
    team_visible: boolean;
  };
  total: number;
  candidates: ListMember[];
}

export interface CandidateLists {
  /** Moje listy (najnowsza na górze — tak sortuje serwer). */
  mine: TalentPoolOut[];
  /** Listy innych osób z „Widzi zespół”. */
  shared: TalentPoolOut[];
}

export const TALENT_POOLS_PREFIX = ["talent-pools"] as const;
export const candidateListsQueryKey = ["talent-pools", "candidate-lists"] as const;
export const listMembersQueryKey = (listId: number) =>
  ["talent-pools", "members", listId] as const;
export const listsForCandidateQueryKey = (candidateId: number) =>
  ["talent-pools", "for-candidate", candidateId] as const;

/** Rozdziela odpowiedź `GET /api/talent-pools` na moje i udostępnione listy. */
export function splitCandidateLists(
  pools: readonly TalentPoolOut[],
  userId: number | null | undefined,
): CandidateLists {
  const lists = pools.filter((p) => p.is_personal && !p.is_marketplace);
  return {
    mine: lists.filter((p) => userId != null && p.owner_id === userId),
    shared: lists.filter((p) => p.owner_id !== userId && p.team_visible),
  };
}

export function memberName(m: Pick<ListMember, "name" | "lastname">): string {
  return `${m.name ?? ""} ${m.lastname ?? ""}`.trim();
}

/** Do trzech umiejętności jako tekst — `skills` z importu bywa listą obiektów. */
export function memberSkills(m: Pick<ListMember, "skills">, limit = 3): string[] {
  const out: string[] = [];
  for (const s of m.skills ?? []) {
    const name =
      typeof s === "string"
        ? s
        : s && typeof s === "object" && "name" in s
          ? String((s as { name: unknown }).name ?? "")
          : "";
    if (name.trim()) out.push(name.trim());
    if (out.length >= limit) break;
  }
  return out;
}

export const candidateListsApi = {
  all: async () => (await api.get<TalentPoolOut[]>("/api/talent-pools")).data,
  members: async (listId: number) =>
    (
      await api.get<ListMembersResponse>(`/api/talent-pools/${listId}/candidates`, {
        params: { limit: 500 },
      })
    ).data,
  forCandidate: async (candidateId: number) =>
    (
      await api.get<{ pool_ids: number[] }>(
        `/api/talent-pools/for-candidate/${candidateId}`,
      )
    ).data.pool_ids,
  /** Nowa lista jest „Tylko ja” (decyzja 25.10.2026). */
  create: async (name: string) =>
    (
      await api.post<TalentPoolOut>("/api/talent-pools", {
        name,
        is_personal: true,
        team_visible: false,
      })
    ).data,
  update: async (listId: number, patch: { name?: string; team_visible?: boolean }) =>
    (await api.patch<TalentPoolOut>(`/api/talent-pools/${listId}`, patch)).data,
  add: async (listId: number, candidateId: number) => {
    await api.post(`/api/talent-pools/${listId}/add`, { candidate_id: candidateId });
  },
  remove: async (listId: number, candidateId: number) => {
    await api.delete(`/api/talent-pools/${listId}/remove/${candidateId}`);
  },
  remove_list: async (listId: number) => {
    await api.delete(`/api/talent-pools/${listId}`);
  },
};

export function useCandidateLists(userId: number | null | undefined, enabled = true) {
  return useQuery({
    queryKey: candidateListsQueryKey,
    queryFn: candidateListsApi.all,
    enabled,
    staleTime: 30_000,
    select: (pools) => splitCandidateLists(pools, userId),
  });
}

export function useListMembers(listId: number | null) {
  return useQuery({
    queryKey: listMembersQueryKey(listId ?? 0),
    queryFn: () => candidateListsApi.members(listId as number),
    enabled: listId != null,
    staleTime: 30_000,
  });
}

export function useListsForCandidate(candidateId: number, enabled = true) {
  return useQuery({
    queryKey: listsForCandidateQueryKey(candidateId),
    queryFn: () => candidateListsApi.forCandidate(candidateId),
    enabled: enabled && Number.isFinite(candidateId),
    staleTime: 30_000,
  });
}
