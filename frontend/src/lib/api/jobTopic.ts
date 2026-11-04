import { useEffect, useRef, useSyncExternalStore } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { WS_BACKED_SAFETY_POLL_MS } from "@/lib/polling";
import { useAuthStore } from "@/store/auth";

/**
 * Jedna pozycja okienka „Rekrutacje” (16.10.2026, w miejscu dzwonka):
 * rekrutacja z powiadomieniami tematu z 7 dni albo pozycja bez rekrutacji
 * (np. poranne „Twoje requesty na dziś”) — wtedy `job_id` jest puste.
 */
export interface JobThread {
  job_id: number | null;
  title: string;
  /** Klient rekrutacji. */
  subtitle: string | null;
  unread_count: number;
  /** Wśród nowych jest coś imiennego (przydział, zadanie stawki…). */
  has_task: boolean;
  last_title: string;
  last_message: string;
  last_at: string | null;
  link: string;
}

export interface JobThreadList {
  items: JobThread[];
  /** Pozycje z nowymi — liczba na ikonie. */
  unread_jobs: number;
}

export type JobTopicTarget =
  | { job_id: number; include_covered?: boolean }
  | { link: string }
  | Record<string, never>;

/** Granica z serwerem: zły kształt to awaria (stan błędu okienka), nie pusta
 *  lista i nie wyjątek w renderze ekranu rekrutacji. */
function parseJobThreadList(data: unknown): JobThreadList {
  const list = data as Partial<JobThreadList> | null;
  if (!list || !Array.isArray(list.items) || typeof list.unread_jobs !== "number") {
    throw new Error("Nieoczekiwana odpowiedź /api/notifications/jobs");
  }
  return list as JobThreadList;
}

export const jobTopicApi = {
  list: () => api.get<JobThreadList>("/api/notifications/jobs"),
  /** Bez celu — wszystkie własne powiadomienia tematu („Oznacz wszystkie”). */
  markRead: async (target: JobTopicTarget = {}): Promise<void> => {
    await api.put("/api/notifications/topics/read", { topic: "jobs", ...target });
  },
};

/** Pod prefiksem `["notifications"]`: gniazdo odświeża go przy każdej ramce. */
export function jobThreadsQueryKey(scopeCacheKey: string): readonly unknown[] {
  return ["notifications", scopeCacheKey, "jobs"];
}

export function useJobThreads() {
  const user = useAuthStore((state) => state.user);
  const scopeCacheKey = `${user?.id ?? "anonymous"}:${user?.authorization_version ?? "none"}`;
  return useQuery({
    queryKey: jobThreadsQueryKey(scopeCacheKey),
    queryFn: () => jobTopicApi.list().then((r) => parseJobThreadList(r.data)),
    enabled: Boolean(user),
    refetchInterval: WS_BACKED_SAFETY_POLL_MS,
  });
}

export function useMarkJobTopicRead() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (target?: JobTopicTarget) => jobTopicApi.markRead(target),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

function subscribeVisibility(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}

function useDocumentVisible(): boolean {
  return useSyncExternalStore(
    subscribeVisibility,
    () => document.visibilityState === "visible",
    () => true,
  );
}

/**
 * Wejście na ekran rekrutacji gasi jej nowości w okienku „Rekrutacje” — jak
 * wejście do czatu gasi rozmowę. Tylko własne wiersze (`include_covered:
 * false`): przypomnienie nieobecnego kolegi zastępca gasi świadomym klikiem.
 * Zapis idzie tylko wtedy, gdy okienko pokazuje nowości tej rekrutacji — ten
 * sam klucz co ikona, więc bez dodatkowego zapytania — i tylko przy widocznej
 * karcie: nowość, która przyszła do karty w tle, czeka na powrót do niej.
 */
export function useClearJobTopic(jobId: number | null | undefined) {
  const threads = useJobThreads().data;
  const visible = useDocumentVisible();
  const markRead = useMarkJobTopicRead();
  const mutateRef = useRef(markRead.mutate);
  mutateRef.current = markRead.mutate;
  const unread =
    jobId && Number.isSafeInteger(jobId)
      ? (threads?.items.find((t) => t.job_id === jobId)?.unread_count ?? 0)
      : 0;
  useEffect(() => {
    if (!jobId || unread <= 0 || !visible) return;
    mutateRef.current({ job_id: jobId, include_covered: false });
  }, [jobId, unread, visible]);
}
