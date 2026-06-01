"use client";

/**
 * Hall of Fame Manager – admin CRUD na dr_competition_winners.
 *
 * Pełen port `HallOfFameManager.tsx` z artur-t-96/InfraReporter (562 linii).
 *
 * Funkcje (DR parity):
 * - Tabela z color-coded competition type chips (purple/blue/green)
 * - Crown/Medal icons per rank (gold/silver/bronze)
 * - Modal "Dodaj/Edytuj zwycięzcę" z:
 *   - Competition type dropdown (3 typy)
 *   - Period dropdown (Q1-Q4 dla quarterly, YYYY-MM dla monthly)
 *   - Rank picker (3 buttons z badges – tylko dla quarterly)
 *   - User dropdown z (name + role)
 *   - Prize text input (opcjonalnie)
 * - Delete confirmation modal
 * - Edit przez upsert (backend ma ON CONFLICT on (competition_type, period, rank))
 */

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Trophy,
  Plus,
  Edit2,
  Trash2,
  X,
  Crown,
  Medal,
  RefreshCw,
  Award,
  AlertCircle,
  CheckCircle,
} from "lucide-react";
import {
  dynareporterRekrutacjaApi,
  dynareporterAdminHofApi,
  dynareporterAdminApi,
  type DrHallOfFameEntry,
  extractErrorMsg,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

const COMPETITION_TYPES = [
  { value: "quarterly", label: "Liga Mistrzów (kwartalna)" },
  {
    value: "monthly_recommendations",
    label: "Wyścig Rekomendacji (miesięczny)",
  },
  { value: "monthly_placements", label: "Wyścig Placementów (miesięczny)" },
] as const;

const MONTHS = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
];

const QUARTERS = ["Q1", "Q2", "Q3", "Q4"];

type CompType =
  | "quarterly"
  | "monthly_recommendations"
  | "monthly_placements";

type FormState = {
  competition_type: CompType;
  period: string;
  user_id: number | null;
  rank: 1 | 2 | 3;
  points: number;
  metric_value: number;
  prize: string;
};

function getPeriodOptions(type: CompType, currentYear: number): string[] {
  const years = [currentYear - 1, currentYear, currentYear + 1];
  const options: string[] = [];
  if (type === "quarterly") {
    for (const y of years) {
      for (const q of QUARTERS) {
        options.push(`${q} ${y}`);
      }
    }
  } else {
    for (const y of years) {
      for (let i = 0; i < 12; i++) {
        const month = String(i + 1).padStart(2, "0");
        options.push(`${y}-${month}`);
      }
    }
  }
  return options;
}

function formatPeriod(period: string, type: CompType): string {
  if (type === "quarterly") {
    return period; // "Q1 2026"
  }
  // "2026-01" → "Styczeń 2026"
  const [year, month] = period.split("-");
  if (!month) return period;
  const m = parseInt(month, 10);
  if (!m || m < 1 || m > 12) return period;
  return `${MONTHS[m - 1]} ${year}`;
}

function RankBadge({ rank, type }: { rank: number; type: CompType }) {
  if (type.startsWith("monthly_")) {
    return (
      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-yellow-400 to-amber-500 flex items-center justify-center">
        <Trophy className="w-4 h-4 text-yellow-900" aria-hidden="true" />
      </div>
    );
  }
  switch (rank) {
    case 1:
      return (
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-yellow-400 to-amber-500 flex items-center justify-center shadow-lg">
          <Crown className="w-4 h-4 text-yellow-900" aria-hidden="true" />
        </div>
      );
    case 2:
      return (
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-gray-300 to-gray-400 flex items-center justify-center">
          <Medal className="w-4 h-4 text-gray-700" aria-hidden="true" />
        </div>
      );
    case 3:
      return (
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-amber-500 to-amber-700 flex items-center justify-center">
          <Medal className="w-4 h-4 text-amber-100" aria-hidden="true" />
        </div>
      );
    default:
      return (
        <span className="text-sm font-medium text-muted-foreground">
          #{rank}
        </span>
      );
  }
}

function CompetitionChip({ type }: { type: CompType }) {
  const config: Record<CompType, { label: string; classes: string }> = {
    quarterly: {
      label: "Liga Mistrzów",
      classes:
        "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
    },
    monthly_recommendations: {
      label: "Rekomendacje",
      classes:
        "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    },
    monthly_placements: {
      label: "Placementy",
      classes:
        "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    },
  };
  const c = config[type];
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${c.classes}`}
    >
      {c.label}
    </span>
  );
}

export function HallOfFameManager() {
  const queryClient = useQueryClient();
  const currentYear = new Date().getFullYear();
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingWinner, setEditingWinner] = useState<DrHallOfFameEntry | null>(
    null,
  );
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [formState, setFormState] = useState<FormState>(() => ({
    competition_type: "quarterly",
    period: `Q${Math.ceil((new Date().getMonth() + 1) / 3)} ${currentYear}`,
    user_id: null,
    rank: 1,
    points: 0,
    metric_value: 0,
    prize: "",
  }));
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
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

  const upsertMutation = useMutation({
    mutationFn: () => {
      if (formState.user_id === null || !formState.period) {
        throw new Error("Wybierz pracownika i okres");
      }
      return dynareporterAdminHofApi.addWinner({
        competition_type: formState.competition_type,
        period: formState.period,
        user_id: formState.user_id,
        rank: formState.rank,
        points: formState.points,
        metric_value: formState.metric_value,
        prize: formState.prize || null,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-hof-all"] });
      queryClient.invalidateQueries({ queryKey: ["dr-rekrutacja-hof"] });
      setMessage({
        type: "success",
        text: editingWinner ? "Wpis zaktualizowany" : "Zwycięzca dodany",
      });
      setShowAddModal(false);
      setEditingWinner(null);
      setTimeout(() => setMessage(null), 3000);
    },
    onError: (e: unknown) => {
      setMessage({ type: "error", text: `Błąd: ${extractErrorMsg(e)}` });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (winnerId: number) =>
      dynareporterAdminHofApi.deleteWinner(winnerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-admin-hof-all"] });
      queryClient.invalidateQueries({ queryKey: ["dr-rekrutacja-hof"] });
      setMessage({ type: "success", text: "Wpis usunięty" });
      setDeletingId(null);
      setTimeout(() => setMessage(null), 3000);
    },
    onError: (e: unknown) => {
      setMessage({
        type: "error",
        text: `Błąd usuwania: ${extractErrorMsg(e)}`,
      });
    },
  });

  const openAddModal = () => {
    setFormState({
      competition_type: "quarterly",
      period: `Q${Math.ceil((new Date().getMonth() + 1) / 3)} ${currentYear}`,
      user_id: null,
      rank: 1,
      points: 0,
      metric_value: 0,
      prize: "",
    });
    setEditingWinner(null);
    setShowAddModal(true);
  };

  const openEditModal = (winner: DrHallOfFameEntry) => {
    setEditingWinner(winner);
    setFormState({
      competition_type: winner.competition_type as CompType,
      period: winner.period,
      user_id: winner.user_id,
      rank: winner.rank as 1 | 2 | 3,
      points: winner.points || 0,
      metric_value: winner.metric_value || 0,
      prize: winner.prize || "",
    });
  };

  const closeModal = () => {
    setShowAddModal(false);
    setEditingWinner(null);
  };

  const handleTypeChange = (newType: string) => {
    const type = newType as CompType;
    const periods = getPeriodOptions(type, currentYear);
    setFormState((prev) => ({
      ...prev,
      competition_type: type,
      period: periods[Math.floor(periods.length / 2)],
      rank: type.startsWith("monthly_") ? 1 : prev.rank,
    }));
  };

  const periodOptions = useMemo(
    () => getPeriodOptions(formState.competition_type, currentYear),
    [formState.competition_type, currentYear],
  );

  const isModalOpen = showAddModal || editingWinner !== null;
  const winners = winnersQuery.data ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-xl">
            <Trophy className="w-6 h-6 text-amber-600 dark:text-amber-400" />
          </div>
          <div>
            <h2 className="text-xl font-bold">Hall of Fame</h2>
            <p className="text-sm text-muted-foreground">
              Zarządzanie zwycięzcami konkursów
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => winnersQuery.refetch()}
            disabled={winnersQuery.isFetching}
            aria-label="Odśwież listę zwycięzców"
          >
            <RefreshCw
              className={`w-4 h-4 ${winnersQuery.isFetching ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
          </Button>
          <Button
            onClick={openAddModal}
            className="bg-amber-600 hover:bg-amber-700"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            <span className="ml-1">Dodaj zwycięzcę</span>
          </Button>
        </div>
      </div>

      {/* Status message */}
      {message && (
        <div
          className={`p-4 rounded-lg flex items-center gap-2 ${
            message.type === "success"
              ? "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400"
              : "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400"
          }`}
        >
          {message.type === "success" ? (
            <Award className="w-5 h-5" />
          ) : (
            <AlertCircle className="w-5 h-5" />
          )}
          <span className="text-sm">{message.text}</span>
        </div>
      )}

      {/* Winners table */}
      <div className="bg-card rounded-xl shadow-sm overflow-hidden border border-border">
        <div className="overflow-x-auto">
          {winnersQuery.isLoading ? (
            <div className="py-12 text-center">
              <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground mx-auto" />
              <p className="text-muted-foreground text-sm mt-2">Ładowanie…</p>
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">
                    Konkurs
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">
                    Okres
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-muted-foreground uppercase">
                    Miejsce
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">
                    Zwycięzca
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">
                    Punkty
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-muted-foreground uppercase">
                    Nagroda
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-muted-foreground uppercase">
                    Akcje
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {winners.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-12 text-center text-muted-foreground"
                    >
                      <Trophy className="w-12 h-12 mx-auto mb-4 opacity-30" />
                      <p>Brak wpisów w Hall of Fame</p>
                      <p className="text-sm mt-1">
                        Kliknij &quot;Dodaj zwycięzcę&quot; aby dodać pierwszy
                        wpis
                      </p>
                    </td>
                  </tr>
                ) : (
                  winners.map((winner: DrHallOfFameEntry) => (
                    <tr key={winner.id} className="hover:bg-muted/40">
                      <td className="px-4 py-3">
                        <CompetitionChip
                          type={winner.competition_type as CompType}
                        />
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {formatPeriod(
                          winner.period,
                          winner.competition_type as CompType,
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-center">
                          <RankBadge
                            rank={winner.rank}
                            type={winner.competition_type as CompType}
                          />
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-sm font-medium">
                          {winner.user_name}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-sm">
                        {winner.points || "–"}
                      </td>
                      <td className="px-4 py-3 text-sm text-amber-600 dark:text-amber-400">
                        {winner.prize || "–"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => openEditModal(winner)}
                          className="p-1.5 text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded mr-1"
                          title="Edytuj"
                          aria-label={`Edytuj zwycięzcę ${winner.user_name}`}
                        >
                          <Edit2 className="w-4 h-4" aria-hidden="true" />
                        </button>
                        <button
                          onClick={() => setDeletingId(winner.id)}
                          className="p-1.5 text-red-600 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                          title="Usuń"
                          aria-label={`Usuń zwycięzcę ${winner.user_name}`}
                        >
                          <Trash2 className="w-4 h-4" aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Add/Edit Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl shadow-xl w-full max-w-md mx-4">
            <div className="px-6 py-4 border-b border-border flex items-center justify-between">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <Trophy className="w-5 h-5 text-amber-500" />
                {editingWinner ? "Edytuj wpis" : "Dodaj zwycięzcę"}
              </h3>
              <button
                onClick={closeModal}
                className="text-muted-foreground hover:text-foreground"
                aria-label="Zamknij modal"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              {/* Competition type */}
              <div>
                <label className="block text-sm font-medium mb-1">
                  Typ konkursu
                </label>
                <select
                  value={formState.competition_type}
                  onChange={(e) => handleTypeChange(e.target.value)}
                  className="w-full px-3 py-2 border border-input rounded-lg bg-background"
                  disabled={!!editingWinner}
                  aria-label="Typ konkursu"
                >
                  {COMPETITION_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Period */}
              <div>
                <label className="block text-sm font-medium mb-1">Okres</label>
                <select
                  value={formState.period}
                  onChange={(e) =>
                    setFormState((prev) => ({ ...prev, period: e.target.value }))
                  }
                  className="w-full px-3 py-2 border border-input rounded-lg bg-background"
                  disabled={!!editingWinner}
                  aria-label="Okres konkursu"
                >
                  {periodOptions.map((p) => (
                    <option key={p} value={p}>
                      {formatPeriod(p, formState.competition_type)}
                    </option>
                  ))}
                </select>
              </div>

              {/* Rank picker (only quarterly) */}
              {formState.competition_type === "quarterly" && (
                <div>
                  <label className="block text-sm font-medium mb-1">
                    Miejsce
                  </label>
                  <div className="flex gap-2">
                    {([1, 2, 3] as const).map((r) => (
                      <button
                        key={r}
                        type="button"
                        onClick={() =>
                          setFormState((prev) => ({ ...prev, rank: r }))
                        }
                        disabled={!!editingWinner}
                        className={`flex-1 py-2 rounded-lg border-2 transition-colors flex items-center justify-center gap-2 ${
                          formState.rank === r
                            ? r === 1
                              ? "border-yellow-500 bg-yellow-50 dark:bg-yellow-900/20"
                              : r === 2
                                ? "border-gray-400 bg-gray-50 dark:bg-gray-700/30"
                                : "border-amber-600 bg-amber-50 dark:bg-amber-900/20"
                            : "border-input hover:border-foreground/30"
                        } ${editingWinner ? "opacity-60" : ""}`}
                        aria-label={`${r}. miejsce`}
                      >
                        <RankBadge rank={r} type="quarterly" />
                        <span className="text-sm font-medium">
                          {r}. miejsce
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* User */}
              <div>
                <label className="block text-sm font-medium mb-1">
                  Zwycięzca
                </label>
                <select
                  value={formState.user_id ?? ""}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      user_id: e.target.value ? Number(e.target.value) : null,
                    }))
                  }
                  className="w-full px-3 py-2 border border-input rounded-lg bg-background"
                  aria-label="Zwycięzca"
                >
                  <option value="">Wybierz pracownika...</option>
                  {(usersQuery.data ?? [])
                    .filter((u) => u.is_active)
                    .map((u) => (
                      <option key={u.id} value={u.id}>
                        {u.name} ({u.role})
                      </option>
                    ))}
                </select>
              </div>

              {/* Points + Metric value */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium mb-1">
                    Punkty
                  </label>
                  <input
                    type="number"
                    min={0}
                    value={formState.points || ""}
                    onChange={(e) =>
                      setFormState((prev) => ({
                        ...prev,
                        points: Number(e.target.value) || 0,
                      }))
                    }
                    placeholder="0"
                    className="w-full px-3 py-2 border border-input rounded-lg bg-background tabular-nums"
                    aria-label="Punkty"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">
                    Metric value
                  </label>
                  <input
                    type="number"
                    min={0}
                    value={formState.metric_value || ""}
                    onChange={(e) =>
                      setFormState((prev) => ({
                        ...prev,
                        metric_value: Number(e.target.value) || 0,
                      }))
                    }
                    placeholder="0"
                    className="w-full px-3 py-2 border border-input rounded-lg bg-background tabular-nums"
                    aria-label="Metric value"
                  />
                </div>
              </div>

              {/* Prize */}
              <div>
                <label className="block text-sm font-medium mb-1">
                  Nagroda (opcjonalnie)
                </label>
                <input
                  type="text"
                  value={formState.prize}
                  onChange={(e) =>
                    setFormState((prev) => ({ ...prev, prize: e.target.value }))
                  }
                  placeholder="np. Voucher 5000 PLN"
                  className="w-full px-3 py-2 border border-input rounded-lg bg-background"
                  aria-label="Nagroda"
                />
              </div>
            </div>

            <div className="px-6 py-4 bg-muted/40 flex justify-end gap-3 rounded-b-xl">
              <button
                onClick={closeModal}
                className="px-4 py-2 hover:bg-muted rounded-lg"
              >
                Anuluj
              </button>
              <button
                onClick={() => upsertMutation.mutate()}
                disabled={
                  upsertMutation.isPending ||
                  formState.user_id === null ||
                  !formState.period
                }
                className="px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50"
              >
                {upsertMutation.isPending ? (
                  <RefreshCw className="w-4 h-4 animate-spin inline" />
                ) : editingWinner ? (
                  "Zapisz zmiany"
                ) : (
                  "Dodaj"
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deletingId !== null && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-card rounded-xl shadow-xl w-full max-w-sm mx-4 p-6">
            <div className="text-center">
              <div className="w-12 h-12 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
                <Trash2 className="w-6 h-6 text-red-600" />
              </div>
              <h3 className="text-lg font-semibold mb-2">Usunąć wpis?</h3>
              <p className="text-sm text-muted-foreground mb-6">
                Ta operacja jest nieodwracalna.
              </p>
              <div className="flex gap-3">
                <button
                  onClick={() => setDeletingId(null)}
                  className="flex-1 px-4 py-2 bg-muted hover:bg-muted/70 rounded-lg"
                  disabled={deleteMutation.isPending}
                >
                  Anuluj
                </button>
                <button
                  onClick={() => deleteMutation.mutate(deletingId)}
                  className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending ? (
                    <RefreshCw className="w-4 h-4 animate-spin inline" />
                  ) : (
                    "Usuń"
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Status icon for success */}
      {message?.type === "success" && (
        <div className="sr-only" role="status">
          <CheckCircle className="w-4 h-4" aria-hidden="true" />
        </div>
      )}
    </div>
  );
}
