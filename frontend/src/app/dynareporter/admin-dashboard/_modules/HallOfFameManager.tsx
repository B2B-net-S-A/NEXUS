"use client";

/**
 * Hall of Fame Manager — admin CRUD na dr_competition_winners.
 * Port `HallOfFameManager.tsx` z artur-t-96/InfraReporter.
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Trophy,
  Plus,
  Trash2,
  Save,
  CheckCircle,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import {
  dynareporterRekrutacjaApi,
  dynareporterAdminHofApi,
  dynareporterAdminApi,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const COMP_LABEL: Record<string, string> = {
  quarterly: "Kwartalna",
  monthly_recommendations: "Miesięczna — Rekomendacje",
  monthly_placements: "Miesięczna — Placementy",
};

export function HallOfFameManager() {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [compType, setCompType] = useState<
    "quarterly" | "monthly_recommendations" | "monthly_placements"
  >("quarterly");
  const [period, setPeriod] = useState("");
  const [userId, setUserId] = useState<number | null>(null);
  const [rank, setRank] = useState<1 | 2 | 3>(1);
  const [points, setPoints] = useState(0);
  const [metricValue, setMetricValue] = useState(0);
  const [prize, setPrize] = useState("");
  const [saveStatus, setSaveStatus] = useState<{
    type: "success" | "error";
    msg: string;
  } | null>(null);

  const winnersQuery = useQuery({
    queryKey: ["dr-admin-hof-all"],
    queryFn: () => dynareporterRekrutacjaApi.hallOfFame(500),
    staleTime: 30_000,
  });

  const usersQuery = useQuery({
    queryKey: ["dr-admin-users-for-hof"],
    queryFn: () => dynareporterAdminApi.users(),
    staleTime: 5 * 60_000,
  });

  const addMutation = useMutation({
    mutationFn: () => {
      if (userId === null || !period)
        throw new Error("Wymagane: period + user");
      return dynareporterAdminHofApi.addWinner({
        competition_type: compType,
        period,
        user_id: userId,
        rank,
        points,
        metric_value: metricValue,
        prize: prize || null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-hof-all"] });
      queryClient.invalidateQueries({ queryKey: ["dr-rekrutacja-hof"] });
      setSaveStatus({ type: "success", msg: "Zwycięzca dodany" });
      setShowForm(false);
      setTimeout(() => setSaveStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setSaveStatus({ type: "error", msg: `Błąd: ${extractErrorMsg(e)}` });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (winnerId: number) =>
      dynareporterAdminHofApi.deleteWinner(winnerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-hof-all"] });
      queryClient.invalidateQueries({ queryKey: ["dr-rekrutacja-hof"] });
      setSaveStatus({ type: "success", msg: "Zwycięzca usunięty" });
      setTimeout(() => setSaveStatus(null), 3000);
    },
    onError: (e: unknown) => {
      setSaveStatus({
        type: "error",
        msg: `Błąd usuwania: ${extractErrorMsg(e)}`,
      });
    },
  });

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Trophy className="w-5 h-5 text-yellow-600" />
            Hall of Fame — Zarządzanie zwycięzcami
          </h3>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => winnersQuery.refetch()}
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
            </Button>
            <Button size="sm" onClick={() => setShowForm((s) => !s)}>
              <Plus className="w-4 h-4" aria-hidden="true" />
              <span className="ml-1">
                {showForm ? "Anuluj" : "Dodaj zwycięzcę"}
              </span>
            </Button>
          </div>
        </div>

        {saveStatus && (
          <div
            className={`mb-3 flex items-center gap-2 text-sm ${saveStatus.type === "success" ? "text-emerald-600" : "text-rose-600"}`}
          >
            {saveStatus.type === "success" ? (
              <CheckCircle className="w-4 h-4" />
            ) : (
              <AlertCircle className="w-4 h-4" />
            )}
            {saveStatus.msg}
          </div>
        )}

        {showForm && (
          <div className="mb-4 p-3 bg-muted/40 rounded grid grid-cols-2 md:grid-cols-4 gap-3">
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Typ
              </label>
              <select
                value={compType}
                onChange={(e) =>
                  setCompType(
                    e.target.value as
                      | "quarterly"
                      | "monthly_recommendations"
                      | "monthly_placements",
                  )
                }
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              >
                <option value="quarterly">Kwartalna</option>
                <option value="monthly_recommendations">
                  Miesięczna — Rek.
                </option>
                <option value="monthly_placements">Miesięczna — Plac.</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Period
              </label>
              <input
                type="text"
                placeholder="Q1 2026 lub 2026-04"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                User
              </label>
              <select
                value={userId ?? ""}
                onChange={(e) =>
                  setUserId(e.target.value ? Number(e.target.value) : null)
                }
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              >
                <option value="">— wybierz —</option>
                {(usersQuery.data ?? [])
                  .filter((u) => u.is_active)
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                    </option>
                  ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Miejsce
              </label>
              <select
                value={rank}
                onChange={(e) => setRank(Number(e.target.value) as 1 | 2 | 3)}
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              >
                <option value={1}>1 🥇</option>
                <option value={2}>2 🥈</option>
                <option value={3}>3 🥉</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Punkty
              </label>
              <input
                type="number"
                min={0}
                value={points}
                onChange={(e) => setPoints(Number(e.target.value))}
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">
                Metric value
              </label>
              <input
                type="number"
                min={0}
                value={metricValue}
                onChange={(e) => setMetricValue(Number(e.target.value))}
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              />
            </div>
            <div className="md:col-span-2">
              <label className="block text-xs text-muted-foreground mb-1">
                Nagroda (opcjonalna)
              </label>
              <input
                type="text"
                placeholder="5000 PLN"
                value={prize}
                onChange={(e) => setPrize(e.target.value)}
                className="w-full px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              />
            </div>
            <div className="md:col-span-4 flex justify-end">
              <Button
                size="sm"
                onClick={() => addMutation.mutate()}
                disabled={addMutation.isPending}
              >
                <Save className="w-4 h-4" aria-hidden="true" />
                <span className="ml-1">Zapisz zwycięzcę</span>
              </Button>
            </div>
          </div>
        )}

        {winnersQuery.isLoading ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            Ładowanie…
          </p>
        ) : !winnersQuery.data || winnersQuery.data.length === 0 ? (
          <p className="text-sm text-muted-foreground py-6 text-center">
            Brak wpisów Hall of Fame.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Period
                  </th>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Typ
                  </th>
                  <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                    Miejsce
                  </th>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Zwycięzca
                  </th>
                  <th className="px-2 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                    Punkty
                  </th>
                  <th className="px-2 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                    Metric
                  </th>
                  <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                    Nagroda
                  </th>
                  <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                    Akcja
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {winnersQuery.data.map((w) => (
                  // Stable PK now that `id` is returned (PR #267).
                  <tr key={w.id}>
                    <td className="px-2 py-1.5 text-xs font-mono">
                      {w.period}
                    </td>
                    <td className="px-2 py-1.5 text-xs text-muted-foreground">
                      {COMP_LABEL[w.competition_type] ?? w.competition_type}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      {w.rank === 1 ? "🥇" : w.rank === 2 ? "🥈" : "🥉"}
                    </td>
                    <td className="px-2 py-1.5 text-sm font-medium">
                      {w.user_name}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-sm">
                      <Badge variant="neutral" size="sm">
                        {w.points || 0}
                      </Badge>
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-sm">
                      {w.metric_value || 0}
                    </td>
                    <td className="px-2 py-1.5 text-xs text-muted-foreground">
                      {w.prize || "—"}
                    </td>
                    <td className="px-2 py-1.5 text-center">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          if (
                            confirm(`Usunąć wpis ${w.user_name} z ${w.period}?`)
                          ) {
                            deleteMutation.mutate(w.id);
                          }
                        }}
                        aria-label={`Usuń ${w.user_name}`}
                      >
                        <Trash2
                          className="w-4 h-4 text-rose-600"
                          aria-hidden="true"
                        />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
