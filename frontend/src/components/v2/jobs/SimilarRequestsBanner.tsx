"use client";

/**
 * Baner „podobne requesty u tego klienta" — wyniesiony z `AddJobModal`
 * (`components/AppShell.tsx`) do `CreateJobModal` (PR 2, przegląd 17.09.2026).
 *
 * Różnica od poprzedniej wersji: zamiast listy linków „Otwórz" bez akcji,
 * każdy wpis dostaje dwie: „Otwórz istniejącą" (tylko gdy request jest w
 * toku — zamknięty nie ma czego kontynuować) i „Użyj jako szablon" (wypełnia
 * formularz treścią source jobu, jak dotychczasowe „Skopiuj jako template"
 * z zakładki Historia). Zapytanie odpytuje się samo (bez bramki
 * `fromJobId == null`) — baner działa też wtedy, gdy DL już wybrał szablon
 * i poprawia tytuł.
 */

import { Sparkles } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  requestHistoryApi,
  type RequestHistoryEntry,
  type RequestHistoryResponse,
} from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { countPl } from "@/lib/plural-pl";

interface SimilarRequestsBannerProps {
  clientId: number | null;
  title: string;
  trainName?: string | null;
  description?: string | null;
  /** `job_id` aktualnie użyty jako szablon (podświetla „Użyto jako szablon"). */
  templateJobId?: number | null;
  onUseAsTemplate: (jobId: number) => void;
}

function statusLabel(entry: RequestHistoryEntry): string {
  if (entry.is_in_progress) return "W toku";
  if (entry.outcome === "filled") return "Obsadzone";
  if (entry.outcome === "cancelled") return "Anulowane";
  return "Zamknięte";
}

function statusTone(entry: RequestHistoryEntry): string {
  if (entry.is_in_progress) {
    return "bg-primary/10 text-primary dark:bg-primary/10 dark:text-primary";
  }
  if (entry.outcome === "filled") {
    return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300";
  }
  return "bg-muted text-muted-foreground";
}

export function SimilarRequestsBanner({
  clientId,
  title,
  trainName,
  description,
  templateJobId = null,
  onUseAsTemplate,
}: SimilarRequestsBannerProps) {
  const debouncedTitle = useDebouncedValue(title, 500);

  const query = useQuery<RequestHistoryResponse>({
    queryKey: ["request-history-preview", clientId, debouncedTitle, trainName ?? null],
    queryFn: async () => {
      const r = await requestHistoryApi.preview({
        title: debouncedTitle,
        client_id: clientId,
        train_name: trainName || null,
        raw_description: description || null,
        top_k: 5,
        cross_client: false,
        include_open: true,
      });
      return r.data;
    },
    enabled: clientId != null && debouncedTitle.length >= 5,
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });

  // Awaria zapytania o podobne requesty MUSI być widoczna — inaczej wygląda
  // jak twierdzenie „u tego klienta nie było nic podobnego" (kolejność jak
  // w TalentRadarResults: błąd przed stanem pustym/sukcesem).
  if (query.isError) {
    return (
      <div
        className="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2 text-xs text-destructive"
        data-testid="request-history-banner-error"
      >
        Nie udało się sprawdzić podobnych requestów u tego klienta — to nie
        znaczy, że ich nie ma. Spróbuj ponownie za chwilę.
      </div>
    );
  }

  if (!query.isSuccess || !query.data) return null;

  const entries = [...query.data.in_progress, ...query.data.closed];
  const total = entries.length;
  if (total === 0) return null;

  return (
    <div
      className="rounded-lg bg-primary/10 dark:bg-primary/10 border border-primary/20 dark:border-primary/30 px-3 py-2 text-xs"
      data-testid="request-history-banner"
    >
      <div className="flex items-center gap-1.5 text-primary dark:text-primary font-medium">
        <Sparkles className="inline w-4 h-4" />
        U tego klienta było już {total}{" "}
        {total === 1 ? "podobny request" : "podobnych requestów"}
        {" "}({query.data.in_progress.length} w toku,{" "}
        {query.data.closed.length} zamkniętych)
      </div>
      <ul className="mt-1.5 space-y-1.5">
        {entries.slice(0, 3).map((entry) => {
          const simPct = Math.round(entry.similarity * 100);
          const isTemplate = templateJobId === entry.job_id;
          return (
            <li
              key={entry.job_id}
              className="flex items-center justify-between gap-2 flex-wrap"
            >
              <span className="truncate">
                {entry.title}{" "}
                <span
                  className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${statusTone(entry)}`}
                >
                  {statusLabel(entry)}
                </span>{" "}
                · {simPct}% ·{" "}
                {countPl(entry.candidates_count, "kandydat", "kandydatów", "kandydatów")}
              </span>
              <span className="flex items-center gap-2 shrink-0">
                {entry.is_in_progress && (
                  <a
                    href={`/jobs/${entry.job_id}`}
                    target="_blank"
                    rel="noreferrer"
                    className="underline hover:text-primary/80"
                  >
                    Otwórz istniejącą
                  </a>
                )}
                {isTemplate ? (
                  <span className="text-emerald-700 dark:text-emerald-400">
                    Użyto jako szablon
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => onUseAsTemplate(entry.job_id)}
                    className="underline hover:text-primary/80"
                  >
                    Użyj jako szablon
                  </button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
