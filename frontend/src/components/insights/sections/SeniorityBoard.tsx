"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { GraduationCap, Loader2 } from "lucide-react";
import {
  insightsApi,
  type SeniorityEntry,
  type SeniorityLevel,
} from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { InsightsSeniority } from "./InsightsSeniority";
import { SectionError } from "./_shared";

const COLUMNS: {
  level: SeniorityLevel;
  label: string;
  dot: string;
  bar: string;
}[] = [
  { level: "junior", label: "Junior", dot: "bg-muted-foreground/50", bar: "bg-muted-foreground/60" },
  { level: "senior", label: "Senior", dot: "bg-primary", bar: "bg-primary" },
  { level: "expert", label: "Expert", dot: "bg-warning", bar: "bg-warning" },
];

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Podpis postępu pod paskiem osoby.
 *
 * `first_placement_month === null` to „nie mamy w NEXUSIE ani jednego
 * placementu tej osoby" — to NIE jest „0 z 6". Taki wiersz dostaje zdanie,
 * a nie pusty pasek, który czytałby się jak werdykt.
 */
export function progressCaption(entry: SeniorityEntry): string {
  if (entry.level === "expert") {
    return entry.expert_since ? `Expert od ${entry.expert_since}` : "Expert";
  }
  if (entry.first_placement_month === null) {
    return "Brak przypisanych placementów";
  }
  if (entry.placements_to_next_level === null) return "Próg wyłączony";
  const next = entry.level === "junior" ? "Seniora" : "Experta";
  const n = entry.placements_to_next_level;
  return n <= 0
    ? `Próg ${next} spełniony`
    : `Do ${next}: brakuje ${n} ${n === 1 ? "placementu" : "placementów"}`;
}

/** Ile kart widać w kolumnie przed „Pokaż wszystkich". */
export const SENIORITY_COLUMN_LIMIT = 6;

/**
 * Ścieżka rozwoju jako tablica Junior / Senior / Expert (21.09.2026).
 *
 * Te same dane co tabela `InsightsSeniority` (ten sam klucz zapytania), inny
 * widok: od razu widać, ile osób stoi na którym poziomie i kto jest blisko
 * awansu. Pełna tabela — z oknami, regresjami i dziennikiem — zostaje pod
 * przyciskiem „Szczegóły".
 */
export function SeniorityBoard() {
  const [showTable, setShowTable] = useState(false);
  // Kolumna Junior bywa trzy razy dłuższa od pozostałych — bez limitu tablica
  // ciągnęła się przez kilka ekranów, a Senior i Expert stały puste obok.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: ["insights", "recruitment", "seniority"],
    queryFn: () => insightsApi.seniority(),
  });

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: (data?.entries.length ?? 0) === 0,
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
            <GraduationCap className="w-5 h-5 text-primary" />
            Ścieżka rozwoju
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Poziom z placementów · raz zdobyty nie spada
            {data ? ` · stan na ${data.as_of}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowTable((v) => !v)}
          aria-expanded={showTable}
          className="text-sm font-semibold text-primary hover:underline"
        >
          {showTable ? "Ukryj szczegóły" : "Szczegóły (tabela, okna, regresje)"}
        </button>
      </div>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Ścieżka rozwoju"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak osób w rolach sourcer / TAC / rekruter.
        </p>
      ) : data ? (
        <div className="grid gap-4 md:grid-cols-3">
          {COLUMNS.map((column) => {
            const people = data.entries
              .filter((e) => e.level === column.level)
              .sort(
                (a, b) =>
                  (b.progress_pct ?? -1) - (a.progress_pct ?? -1) ||
                  b.total_placements - a.total_placements,
              );
            return (
              <div
                key={column.level}
                className="rounded-xl bg-muted/50 p-3 space-y-2"
                data-testid={`seniority-column-${column.level}`}
              >
                <div className="flex items-center gap-2 px-1 pb-1">
                  <span className={cn("h-2.5 w-2.5 rounded-sm", column.dot)} />
                  <span className="text-sm font-semibold text-foreground">
                    {column.label}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {people.length}
                  </span>
                </div>
                {people.length === 0 ? (
                  <p className="px-1 py-3 text-xs text-muted-foreground">
                    Nikt na tym poziomie.
                  </p>
                ) : (
                  (expanded[column.level]
                    ? people
                    : people.slice(0, SENIORITY_COLUMN_LIMIT)
                  ).map((entry) => {
                    const pct =
                      entry.level === "expert"
                        ? 100
                        : Math.max(0, Math.min(100, entry.progress_pct ?? 0));
                    const noData =
                      entry.level !== "expert" &&
                      (entry.first_placement_month === null ||
                        entry.progress_pct === null);
                    return (
                      <div
                        key={entry.user_id}
                        className="rounded-lg border border-border bg-card p-3 space-y-2"
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                            {initials(entry.name)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-semibold text-foreground">
                              {entry.name}
                            </div>
                            <div className="text-xs text-muted-foreground">
                              {entry.total_placements} plac. łącznie
                            </div>
                          </div>
                        </div>
                        {noData ? null : (
                          <div className="h-1.5 rounded-full bg-muted">
                            <div
                              className={cn("h-1.5 rounded-full", column.bar)}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        )}
                        <div className="text-xs text-muted-foreground">
                          {progressCaption(entry)}
                        </div>
                      </div>
                    );
                  })
                )}
                {people.length > SENIORITY_COLUMN_LIMIT ? (
                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((prev) => ({
                        ...prev,
                        [column.level]: !prev[column.level],
                      }))
                    }
                    aria-expanded={!!expanded[column.level]}
                    className="w-full rounded-lg px-2 py-1.5 text-xs font-semibold text-primary hover:bg-card"
                  >
                    {expanded[column.level]
                      ? "Pokaż mniej"
                      : `Pokaż wszystkich (${people.length})`}
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : null}

      {showTable ? <InsightsSeniority /> : null}
    </section>
  );
}
