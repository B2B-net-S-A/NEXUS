"use client";

/**
 * „Utknęli w lekcjach” (Artur, 23.11.2026): kto trzy razy nie przeszedł
 * etapu „sam” w tej samej lekcji nowości. To temat na szkolenie, nie kara —
 * imiennie, więc tylko admin i Head of Recruitment (jak panel „kto umie”).
 */

import { useQuery } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { api } from "@/lib/api";
import { resolveViewState } from "@/lib/view-state";

export interface LessonStruggle {
  user_id: number;
  name: string;
  lesson_id: string;
  title: string;
  solo_failed_count: number;
  quiz_wrong_count: number;
  updated_at: string;
}

export const strugglesKey = ["novelties", "lessons", "struggles"] as const;

const DAY = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "short", timeZone: "Europe/Warsaw" });

export function LessonStruggles() {
  const query = useQuery({
    queryKey: strugglesKey,
    queryFn: async () => (await api.get<LessonStruggle[]>("/api/novelties/lessons/struggles")).data,
    staleTime: 60_000,
  });
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: (query.data ?? []).length === 0,
  });
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4" aria-label="Utknęli w lekcjach">
      <div>
        <h2 className="text-sm font-semibold">Utknęli w lekcjach nowości</h2>
        <p className="text-xs text-muted-foreground">
          Trzy i więcej nieudanych prób samodzielnych w tej samej lekcji. Warto to pokazać na szkoleniu.
        </p>
      </div>
      {state === "loading" ? <p className="text-xs text-muted-foreground">Wczytuję…</p> : null}
      {state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => query.refetch()} />
      ) : null}
      {state === "empty" ? <p className="text-xs text-muted-foreground">Nikt nie utknął.</p> : null}
      {state === "ready" ? (
        <ul className="divide-y divide-border text-sm">
          {(query.data ?? []).map((s) => (
            <li key={`${s.user_id}-${s.lesson_id}`} className="flex flex-wrap items-baseline gap-x-3 py-1.5">
              <span className="font-medium">{s.name}</span>
              <span className="min-w-0 flex-1 text-muted-foreground">{s.title}</span>
              <span className="text-xs tabular-nums text-muted-foreground">
                {s.solo_failed_count} prób · {DAY.format(new Date(s.updated_at))}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
