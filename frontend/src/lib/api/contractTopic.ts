import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";

/**
 * Jedna pozycja okienka „Umowy” (26.10.2026): umowa w podpisie z ostatnim
 * zdarzeniem — czeka na Twój podpis, kontraktor podpisał, podpisana, link
 * wygasł, prośba o potwierdzenie podpisu. Reprezentant firmy nie zauważył
 * umowy, bo te zdarzenia nie miały ikony na pasku.
 */
export interface ContractThread {
  key: string;
  title: string;
  message: string;
  unread_count: number;
  /** Nieprzeczytane wiersze tej pozycji — klik gasi je przez `topics/read`. */
  unread_ids: number[];
  last_at: string | null;
  link: string;
}

export interface ContractThreadList {
  items: ContractThread[];
  /** Umowy z nowymi — liczba na ikonie. */
  unread_contracts: number;
}

export type ContractTopicTarget = { ids: number[] } | Record<string, never>;

/** Granica z serwerem: zły kształt to awaria (stan błędu okienka), nie pusta lista. */
function parseContractThreadList(data: unknown): ContractThreadList {
  const list = data as Partial<ContractThreadList> | null;
  if (!list || !Array.isArray(list.items) || typeof list.unread_contracts !== "number") {
    throw new Error("Nieoczekiwana odpowiedź /api/notifications/contracts");
  }
  return list as ContractThreadList;
}

export const contractTopicApi = {
  list: () => api.get<ContractThreadList>("/api/notifications/contracts"),
  /** Bez celu — wszystkie własne powiadomienia tematu („Oznacz wszystkie”). */
  markRead: async (target: ContractTopicTarget = {}): Promise<void> => {
    await api.put("/api/notifications/topics/read", { topic: "contracts", ...target });
  },
};

/** Pod prefiksem `["notifications"]`: gniazdo odświeża go przy każdej ramce. */
export function contractThreadsQueryKey(scopeCacheKey: string): readonly unknown[] {
  return ["notifications", scopeCacheKey, "contracts"];
}

export function useContractThreads() {
  const user = useAuthStore((state) => state.user);
  const scopeCacheKey = `${user?.id ?? "anonymous"}:${user?.authorization_version ?? "none"}`;
  return useQuery({
    queryKey: contractThreadsQueryKey(scopeCacheKey),
    queryFn: () => contractTopicApi.list().then((r) => parseContractThreadList(r.data)),
    enabled: Boolean(user),
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
  });
}

export function useMarkContractTopicRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (target?: ContractTopicTarget) => contractTopicApi.markRead(target),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
