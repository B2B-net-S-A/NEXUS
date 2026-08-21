"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Award,
  Briefcase,
  CheckCircle,
  Phone,
  Trophy,
  Users,
  Zap,
} from "lucide-react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { PERIOD_LABELS, type Period } from "./PeriodSelector";
import { SectionError } from "./_shared";

interface LeaderboardRow {
  user_id: number;
  user_name: string;
  rank: number;
  candidates_added: number;
  screenings: number;
  interviews: number;
  placements: number;
  calls: number;
  total_actions: number;
}

const ACTIVITY_TYPES = [
  "candidates_added",
  "screenings",
  "interviews",
  "placements",
  "calls",
] as const;

const TYPE_LABELS: Record<(typeof ACTIVITY_TYPES)[number], string> = {
  candidates_added: "Kandydaci",
  screenings: "Screeningi",
  interviews: "Interviews",
  placements: "Placements",
  calls: "Telefony",
};

const HEAT_COLORS = [
  "bg-primary",
  "bg-indigo-500",
  "bg-purple-500",
  "bg-green-500",
  "bg-orange-500",
];

interface Props {
  period: Period;
}

export function ActivityHeatmap({ period }: Props) {
  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ["insights-leaderboard", period],
    queryFn: () =>
      api
        .get<{ leaderboard: LeaderboardRow[]; since?: string }>(
          `/api/activities/leaderboard?period=${period}&limit=20`
        )
        .then((r) => r.data),
  });

  const rows = data?.leaderboard ?? [];
  const maxActions = rows.length > 0 ? Math.max(...rows.map((r) => r.total_actions), 1) : 1;
  // „Brak danych dla wybranego okresu" to zdanie o zespole. Gdy leaderboard
  // padnie, prawdą jest „nie wiemy" — i tego nie wolno mylić z zerem aktywności
  // (audyt F-20). `isPending`, nie `isLoading` — patrz komentarz w BoardKPI.
  const viewState = resolveViewState({
    isLoading: isPending,
    isError,
    error,
    isEmpty: rows.length === 0,
  });

  return (
    <section className="space-y-4">
      {/* Heatmap card */}
      <div className="bg-card rounded-xl border border-border p-6 shadow-xs">
        <div className="flex items-center gap-2 mb-5">
          <Zap className="w-5 h-5 text-amber-500" />
          <h2 className="text-base font-semibold text-foreground">Aktywność zespołu</h2>
          <span className="ml-auto text-xs text-muted-foreground">
            {PERIOD_LABELS[period]}
          </span>
        </div>

        {viewState === "loading" ? (
          <div className="py-8 text-center text-muted-foreground">Ładowanie danych...</div>
        ) : isBlockingViewState(viewState) ? (
          <SectionError
            label="Aktywność zespołu"
            error={error}
            onRetry={() => void refetch()}
          />
        ) : viewState === "empty" ? (
          <div className="py-8 text-center text-muted-foreground">
            Brak danych dla wybranego okresu
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  <th className="text-left pb-2 pr-4 text-muted-foreground font-medium w-32">
                    Rekruter
                  </th>
                  {ACTIVITY_TYPES.map((t) => (
                    <th
                      key={t}
                      className="pb-2 px-1 text-muted-foreground font-medium text-center w-20"
                    >
                      {TYPE_LABELS[t]}
                    </th>
                  ))}
                  <th className="pb-2 px-1 text-muted-foreground font-medium text-center">
                    Razem
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 10).map((row) => {
                  const values = [
                    row.candidates_added,
                    row.screenings,
                    row.interviews,
                    row.placements,
                    row.calls,
                  ];
                  const max = Math.max(...values, 1);
                  return (
                    <tr key={row.user_id} className="border-t border-border/50">
                      <td className="py-2 pr-4 font-medium text-foreground truncate max-w-32">
                        {row.user_name}
                      </td>
                      {values.map((v, i) => {
                        const intensity = max > 0 ? v / max : 0;
                        return (
                          <td key={i} className="py-2 px-1 text-center">
                            <div
                              className={cn(
                                "w-10 h-8 rounded flex items-center justify-center mx-auto text-xs font-semibold transition-all",
                                v > 0 ? HEAT_COLORS[i] : "bg-muted",
                                v > 0 ? "text-white" : "text-muted-foreground"
                              )}
                              style={{ opacity: v > 0 ? Math.max(0.3 + intensity * 0.7, 0.3) : 1 }}
                              title={`${TYPE_LABELS[ACTIVITY_TYPES[i]]}: ${v}`}
                            >
                              {v}
                            </div>
                          </td>
                        );
                      })}
                      <td className="py-2 px-1 text-center">
                        <span className="font-bold text-foreground">{row.total_actions}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Top 5 + detailed table — pokazujemy tylko gdy są dane */}
      {rows.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="bg-card rounded-xl border border-border p-6 shadow-xs">
            <div className="flex items-center gap-2 mb-5">
              <Trophy className="w-5 h-5 text-yellow-500" />
              <h2 className="text-base font-semibold text-foreground">
                Top 5 — aktywność łączna
              </h2>
            </div>
            <div className="space-y-3">
              {rows.slice(0, 5).map((row, i) => (
                <div key={row.user_id} className="flex items-center gap-3">
                  <div className="w-6 text-center">
                    <span
                      className={cn(
                        "text-sm font-bold",
                        i === 0
                          ? "text-yellow-500"
                          : i === 1
                          ? "text-muted-foreground"
                          : i === 2
                          ? "text-orange-400"
                          : "text-muted-foreground"
                      )}
                    >
                      {i + 1}
                    </span>
                  </div>
                  <div className="w-32 truncate text-sm font-medium text-foreground">
                    {row.user_name}
                  </div>
                  <div className="flex-1">
                    <div className="w-full bg-muted rounded-full h-6 relative">
                      <div
                        className={cn(
                          "h-6 rounded-full transition-all duration-500",
                          i === 0
                            ? "bg-primary"
                            : i === 1
                            ? "bg-primary/40"
                            : i === 2
                            ? "bg-primary/30"
                            : "bg-primary/20"
                        )}
                        style={{ width: `${(row.total_actions / maxActions) * 100}%` }}
                      />
                      <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-foreground">
                        {row.total_actions}
                      </span>
                    </div>
                  </div>
                  <div className="w-12 text-right text-sm text-green-600 font-semibold">
                    {row.placements > 0 ? `${row.placements} 🏆` : ""}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="bg-card rounded-xl border border-border p-6 shadow-xs overflow-hidden">
            <div className="flex items-center gap-2 mb-4">
              <Users className="w-5 h-5 text-muted-foreground" />
              <h2 className="text-base font-semibold text-foreground">Pełna tabela</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-2 px-2 text-muted-foreground font-medium">#</th>
                    <th className="text-left py-2 px-2 text-muted-foreground font-medium">
                      Rekruter
                    </th>
                    <th className="text-right py-2 px-2 text-muted-foreground font-medium">
                      <Users className="w-3 h-3 inline" />
                    </th>
                    <th className="text-right py-2 px-2 text-muted-foreground font-medium">
                      <CheckCircle className="w-3 h-3 inline" />
                    </th>
                    <th className="text-right py-2 px-2 text-muted-foreground font-medium">
                      <Briefcase className="w-3 h-3 inline" />
                    </th>
                    <th className="text-right py-2 px-2 text-muted-foreground font-medium">
                      <Award className="w-3 h-3 inline" />
                    </th>
                    <th className="text-right py-2 px-2 text-muted-foreground font-medium">
                      <Phone className="w-3 h-3 inline" />
                    </th>
                    <th className="text-right py-2 px-2 text-muted-foreground font-medium">Σ</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.user_id}
                      className="border-b border-border/50 hover:bg-muted/30"
                    >
                      <td className="py-2 px-2">
                        <span
                          className={cn(
                            "font-bold",
                            row.rank === 1
                              ? "text-yellow-500"
                              : row.rank === 2
                              ? "text-muted-foreground"
                              : row.rank === 3
                              ? "text-orange-400"
                              : "text-muted-foreground"
                          )}
                        >
                          {row.rank}
                        </span>
                      </td>
                      <td className="py-2 px-2 font-medium text-foreground">{row.user_name}</td>
                      <td className="py-2 px-2 text-right text-primary font-medium">
                        {row.candidates_added}
                      </td>
                      <td className="py-2 px-2 text-right">{row.screenings}</td>
                      <td className="py-2 px-2 text-right">{row.interviews}</td>
                      <td className="py-2 px-2 text-right">
                        <span
                          className={
                            row.placements > 0 ? "text-green-600 font-semibold" : "text-muted-foreground"
                          }
                        >
                          {row.placements}
                        </span>
                      </td>
                      <td className="py-2 px-2 text-right">{row.calls}</td>
                      <td className="py-2 px-2 text-right font-bold">{row.total_actions}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
