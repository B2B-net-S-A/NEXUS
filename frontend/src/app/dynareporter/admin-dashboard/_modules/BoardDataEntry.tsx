"use client";

/**
 * Board Data Entry — admin formularz miesięcznych raportów Rady Nadzorczej.
 *
 * Pełen port `BoardDataEntry.tsx` z artur-t-96/InfraReporter (536 linii).
 *
 * Funkcje (DR parity):
 * - Month dropdown picker (Sty 2024 – Gru 2026, 36 miesięcy)
 * - 3-section colored layout: Finanse (emerald) / HR (blue) / Wskaźniki (amber)
 * - Auto-calculated Marża + Zysk (readonly z color-coded green/red)
 * - Placement clients editor: master_data dropdown + custom client input + count
 * - Overview table na dole — wszystkie miesiące grouped per year + Suma row
 * - Edit/Delete actions per row
 */

import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Save,
  RefreshCw,
  DollarSign,
  Users,
  Target,
  Plus,
  X,
  AlertCircle,
  CheckCircle,
  Edit2,
  Trash2,
  Calendar,
} from "lucide-react";
import {
  dynareporterBoardApi,
  dynareporterBoardAdminApi,
  dynareporterAdminMasterDataApi,
  type DrBoardPlacementClient,
  type DrBoardMonthlyRow,
  extractErrorMsg,
} from "@/lib/api";
import { Button } from "@/components/ui/button";

const MONTH_NAMES = [
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

function formatMonth(monthStr: string): string {
  const [year, month] = monthStr.split("-");
  return `${MONTH_NAMES[parseInt(month, 10) - 1]} ${year}`;
}

function formatPLN(value: number): string {
  return (value || 0).toLocaleString("pl-PL") + " zł";
}

function formatClientsTooltip(clients: DrBoardPlacementClient[]): string {
  if (!clients || clients.length === 0) return "";
  return clients.map((c) => `${c.client_name} (${c.count})`).join(", ");
}

type FormData = {
  revenue: number;
  consultantCosts: number;
  otherCosts: number;
  activeConsultants: number;
  departures: number;
  placements: number;
  avgMarginPerHour: number;
  hitRatio: number;
  clients: DrBoardPlacementClient[];
};

const EMPTY_FORM: FormData = {
  revenue: 0,
  consultantCosts: 0,
  otherCosts: 0,
  activeConsultants: 0,
  departures: 0,
  placements: 0,
  avgMarginPerHour: 0,
  hitRatio: 0,
  clients: [],
};

export function BoardDataEntry() {
  const queryClient = useQueryClient();
  const now = new Date();
  const currentYM = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [reportMonth, setReportMonth] = useState(currentYM);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [customClientIdx, setCustomClientIdx] = useState<Set<number>>(
    () => new Set(),
  );
  const [message, setMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // 36-month dropdown options (2024-01 to 2026-12, newest first)
  const monthOptions = useMemo(() => {
    const months: string[] = [];
    for (let year = 2024; year <= 2026; year++) {
      for (let month = 1; month <= 12; month++) {
        months.push(`${year}-${String(month).padStart(2, "0")}`);
      }
    }
    return months.reverse();
  }, []);

  const monthlyQuery = useQuery({
    queryKey: ["dr-board-monthly-admin"],
    queryFn: () => dynareporterBoardApi.monthly(),
    staleTime: 30_000,
  });

  const clientsQuery = useQuery({
    queryKey: ["dr-admin-master-clients"],
    queryFn: () => dynareporterAdminMasterDataApi.clients(),
    staleTime: 5 * 60_000,
  });

  // Auto-load existing data when month changes
  useEffect(() => {
    if (!monthlyQuery.data) return;
    const found = monthlyQuery.data.find((r) => r.report_month === reportMonth);
    if (found) {
      setForm({
        revenue: found.revenue,
        consultantCosts: found.consultant_costs,
        otherCosts: found.other_costs,
        activeConsultants: found.active_consultants,
        departures: found.departures,
        placements: found.placements,
        avgMarginPerHour: found.avg_margin_per_hour,
        hitRatio: found.hit_ratio,
        clients: found.placement_clients,
      });
    } else {
      setForm(EMPTY_FORM);
    }
    setCustomClientIdx(new Set());
  }, [monthlyQuery.data, reportMonth]);

  const upsertMutation = useMutation({
    mutationFn: () =>
      dynareporterBoardAdminApi.upsert({
        report_month: reportMonth,
        revenue: form.revenue,
        consultant_costs: form.consultantCosts,
        other_costs: form.otherCosts,
        active_consultants: form.activeConsultants,
        departures: form.departures,
        placements: form.placements,
        avg_margin_per_hour: form.avgMarginPerHour,
        hit_ratio: form.hitRatio,
        placement_clients: form.clients.filter(
          (c) => c.client_name && c.client_name.trim() && c.count > 0,
        ),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-board-monthly"] });
      queryClient.invalidateQueries({ queryKey: ["dr-board-monthly-admin"] });
      setMessage({
        type: "success",
        text: `Dane za ${formatMonth(reportMonth)} zapisane`,
      });
      setTimeout(() => setMessage(null), 4000);
    },
    onError: (e: unknown) => {
      setMessage({ type: "error", text: `Błąd: ${extractErrorMsg(e)}` });
    },
  });

  const setField = <K extends keyof FormData>(field: K, value: FormData[K]) =>
    setForm((prev) => ({ ...prev, [field]: value }));

  const margin = form.revenue - form.consultantCosts;
  const profit = margin - form.otherCosts;
  const placementClientsSum = form.clients.reduce(
    (s, c) => s + (c.count || 0),
    0,
  );

  const addPlacementClient = () => {
    setForm((prev) => ({
      ...prev,
      clients: [...prev.clients, { client_name: "", count: 0 }],
    }));
  };

  const updatePlacementClient = (
    index: number,
    field: "client_name" | "count",
    value: string | number,
  ) => {
    setForm((prev) => ({
      ...prev,
      clients: prev.clients.map((c, i) =>
        i === index ? { ...c, [field]: value } : c,
      ),
    }));
  };

  const removePlacementClient = (index: number) => {
    setForm((prev) => ({
      ...prev,
      clients: prev.clients.filter((_, i) => i !== index),
    }));
    setCustomClientIdx((prev) => {
      const n = new Set(prev);
      n.delete(index);
      return n;
    });
  };

  const inputClass =
    "w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-background text-right text-sm";
  const readonlyClass =
    "w-full px-3 py-2 border border-gray-200 dark:border-gray-600 rounded-lg bg-muted text-right text-sm font-medium";

  return (
    <div className="space-y-4">
      {/* Nagłówek */}
      <div className="bg-card rounded-xl p-4 shadow-sm border border-border">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Target className="w-5 h-5 text-indigo-600" />
            <span className="font-medium">Dane Rady Nadzorczej</span>
          </div>

          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            <select
              value={reportMonth}
              onChange={(e) => setReportMonth(e.target.value)}
              className="px-3 py-1.5 border border-input rounded-lg bg-background text-sm"
              aria-label="Wybierz miesiąc"
            >
              {monthOptions.map((m) => (
                <option key={m} value={m}>
                  {formatMonth(m)}
                </option>
              ))}
            </select>
          </div>

          <div className="flex-1" />

          <Button
            variant="outline"
            size="sm"
            onClick={() => monthlyQuery.refetch()}
            disabled={monthlyQuery.isFetching}
            aria-label="Odśwież dane"
          >
            <RefreshCw
              className={`w-4 h-4 ${monthlyQuery.isFetching ? "animate-spin" : ""}`}
              aria-hidden="true"
            />
          </Button>
          <Button
            size="sm"
            onClick={() => upsertMutation.mutate()}
            disabled={upsertMutation.isPending}
            className="bg-green-600 hover:bg-green-700"
          >
            {upsertMutation.isPending ? (
              <RefreshCw className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            <span className="ml-1">Zapisz dane</span>
          </Button>
        </div>

        {message && (
          <div
            className={`mt-4 p-3 rounded-lg flex items-center gap-2 ${
              message.type === "success"
                ? "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                : "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400"
            }`}
          >
            {message.type === "success" ? (
              <CheckCircle className="w-5 h-5" />
            ) : (
              <AlertCircle className="w-5 h-5" />
            )}
            <span className="text-sm">{message.text}</span>
          </div>
        )}
      </div>

      {monthlyQuery.isLoading ? (
        <div className="bg-card rounded-xl p-8 shadow-sm border border-border flex justify-center">
          <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Sekcja Finanse */}
          <div className="bg-card rounded-xl p-5 shadow-sm border border-emerald-200 dark:border-emerald-800">
            <div className="flex items-center gap-2 mb-5">
              <DollarSign className="w-5 h-5 text-emerald-600" />
              <h3 className="font-semibold text-emerald-900 dark:text-emerald-100">
                Finanse
              </h3>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-muted-foreground mb-1">
                  Przychody (PLN)
                </label>
                <input
                  type="number"
                  value={form.revenue || ""}
                  onChange={(e) =>
                    setField("revenue", Number(e.target.value) || 0)
                  }
                  className={inputClass}
                  placeholder="0"
                  aria-label="Przychody w PLN"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-1">
                  Koszty konsultantów (PLN)
                </label>
                <input
                  type="number"
                  value={form.consultantCosts || ""}
                  onChange={(e) =>
                    setField("consultantCosts", Number(e.target.value) || 0)
                  }
                  className={inputClass}
                  placeholder="0"
                  aria-label="Koszty konsultantów w PLN"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-1">
                  Pozostałe koszty (PLN)
                </label>
                <input
                  type="number"
                  value={form.otherCosts || ""}
                  onChange={(e) =>
                    setField("otherCosts", Number(e.target.value) || 0)
                  }
                  className={inputClass}
                  placeholder="0"
                  aria-label="Pozostałe koszty w PLN"
                />
              </div>
              <div className="pt-3 border-t border-border space-y-3">
                <div>
                  <label className="block text-sm text-muted-foreground mb-1">
                    Marża (auto)
                  </label>
                  <div
                    className={`${readonlyClass} ${margin >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
                  >
                    {formatPLN(margin)}
                  </div>
                </div>
                <div>
                  <label className="block text-sm text-muted-foreground mb-1">
                    Zysk (auto)
                  </label>
                  <div
                    className={`${readonlyClass} ${profit >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
                  >
                    {formatPLN(profit)}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Sekcja HR */}
          <div className="bg-card rounded-xl p-5 shadow-sm border border-blue-200 dark:border-blue-800">
            <div className="flex items-center gap-2 mb-5">
              <Users className="w-5 h-5 text-blue-600" />
              <h3 className="font-semibold text-blue-900 dark:text-blue-100">
                HR
              </h3>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-muted-foreground mb-1">
                  Liczba konsultantów
                </label>
                <input
                  type="number"
                  value={form.activeConsultants || ""}
                  onChange={(e) =>
                    setField("activeConsultants", Number(e.target.value) || 0)
                  }
                  className={inputClass}
                  placeholder="0"
                  aria-label="Liczba aktywnych konsultantów"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-1">
                  Liczba zejść
                </label>
                <input
                  type="number"
                  value={form.departures || ""}
                  onChange={(e) =>
                    setField("departures", Number(e.target.value) || 0)
                  }
                  className={inputClass}
                  placeholder="0"
                  aria-label="Liczba zejść konsultantów"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-1">
                  Liczba placementów
                </label>
                <input
                  type="number"
                  value={form.placements || ""}
                  onChange={(e) =>
                    setField("placements", Number(e.target.value) || 0)
                  }
                  className={inputClass}
                  placeholder="0"
                  aria-label="Liczba placementów"
                />
              </div>

              {/* Rozbicie placementów na klientów */}
              <div className="pt-3 border-t border-border">
                <div className="flex items-center justify-between mb-2">
                  <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    Klienci
                  </label>
                  {placementClientsSum > 0 && (
                    <span className="text-xs text-muted-foreground">
                      Suma: {placementClientsSum}
                    </span>
                  )}
                </div>
                <div className="space-y-2">
                  {form.clients.map((pc, idx) => {
                    const isCustom = customClientIdx.has(idx);
                    const isOnList = clientsQuery.data?.some(
                      (c) => c.name === pc.client_name,
                    );
                    const showCustomInput =
                      isCustom || (pc.client_name && !isOnList);

                    return (
                      <div key={idx} className="flex gap-2 items-center">
                        {showCustomInput ? (
                          <div className="flex-1 flex gap-1">
                            <input
                              type="text"
                              value={pc.client_name}
                              onChange={(e) =>
                                updatePlacementClient(
                                  idx,
                                  "client_name",
                                  e.target.value,
                                )
                              }
                              className="flex-1 px-2 py-1.5 border border-input rounded-lg bg-background text-sm"
                              placeholder="Nazwa klienta"
                              aria-label={`Nazwa klienta ${idx + 1}`}
                            />
                            <button
                              onClick={() => {
                                setCustomClientIdx((prev) => {
                                  const n = new Set(prev);
                                  n.delete(idx);
                                  return n;
                                });
                                updatePlacementClient(idx, "client_name", "");
                              }}
                              className="p-1 text-muted-foreground hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/30 rounded transition-colors"
                              title="Wybierz z listy"
                              aria-label="Powrót do listy klientów"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        ) : (
                          <select
                            value={pc.client_name}
                            onChange={(e) => {
                              if (e.target.value === "__custom__") {
                                setCustomClientIdx((prev) =>
                                  new Set(prev).add(idx),
                                );
                                updatePlacementClient(idx, "client_name", "");
                              } else {
                                updatePlacementClient(
                                  idx,
                                  "client_name",
                                  e.target.value,
                                );
                              }
                            }}
                            className="flex-1 px-2 py-1.5 border border-input rounded-lg bg-background text-sm"
                            aria-label={`Klient ${idx + 1}`}
                          >
                            <option value="">Wybierz klienta...</option>
                            {clientsQuery.data?.map((c) => (
                              <option key={c.id} value={c.name}>
                                {c.name}
                              </option>
                            ))}
                            <option value="__custom__">
                              — Inny (wpisz ręcznie) —
                            </option>
                          </select>
                        )}
                        <input
                          type="number"
                          value={pc.count || ""}
                          onChange={(e) =>
                            updatePlacementClient(
                              idx,
                              "count",
                              Number(e.target.value) || 0,
                            )
                          }
                          className="w-16 px-2 py-1.5 border border-input rounded-lg bg-background text-right text-sm"
                          placeholder="0"
                          aria-label={`Liczba placementów dla klienta ${idx + 1}`}
                        />
                        <button
                          onClick={() => removePlacementClient(idx)}
                          className="p-1 text-red-500 hover:bg-red-100 dark:hover:bg-red-900/30 rounded transition-colors"
                          aria-label={`Usuń klienta ${idx + 1}`}
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    );
                  })}
                  <button
                    onClick={addPlacementClient}
                    className="flex items-center gap-1 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 mt-1"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Dodaj klienta
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Sekcja Wskaźniki operacyjne */}
          <div className="bg-card rounded-xl p-5 shadow-sm border border-amber-200 dark:border-amber-800">
            <div className="flex items-center gap-2 mb-5">
              <Target className="w-5 h-5 text-amber-600" />
              <h3 className="font-semibold text-amber-900 dark:text-amber-100">
                Wskaźniki operacyjne
              </h3>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-muted-foreground mb-1">
                  Średnia marża na konsultancie (PLN/h)
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={form.avgMarginPerHour || ""}
                  onChange={(e) =>
                    setField("avgMarginPerHour", Number(e.target.value) || 0)
                  }
                  className={inputClass}
                  placeholder="0.00"
                  aria-label="Średnia marża na konsultancie w PLN na godzinę"
                />
              </div>
              <div>
                <label className="block text-sm text-muted-foreground mb-1">
                  Średnie hit ratio (%)
                </label>
                <input
                  type="number"
                  step="0.1"
                  value={form.hitRatio || ""}
                  onChange={(e) =>
                    setField("hitRatio", Number(e.target.value) || 0)
                  }
                  className={inputClass}
                  placeholder="0.0"
                  aria-label="Średnie hit ratio w procentach"
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tabela przeglądowa — wszystkie miesiące grouped per year */}
      {monthlyQuery.data && monthlyQuery.data.length > 0 && (
        <OverviewTable
          rows={monthlyQuery.data}
          selectedMonth={reportMonth}
          onEdit={setReportMonth}
          onDelete={async (monthStr) => {
            if (!window.confirm(`Usunąć dane za ${formatMonth(monthStr)}?`))
              return;
            try {
              await dynareporterBoardAdminApi.deleteMonthly(monthStr);
              queryClient.invalidateQueries({
                queryKey: ["dr-board-monthly-admin"],
              });
              queryClient.invalidateQueries({
                queryKey: ["dr-board-monthly"],
              });
              setMessage({
                type: "success",
                text: `Usunięto dane za ${formatMonth(monthStr)}`,
              });
              setTimeout(() => setMessage(null), 3000);
            } catch (e: unknown) {
              setMessage({
                type: "error",
                text: `Błąd: ${extractErrorMsg(e)}`,
              });
            }
          }}
        />
      )}
    </div>
  );
}

function OverviewTable({
  rows,
  selectedMonth,
  onEdit,
  onDelete,
}: {
  rows: DrBoardMonthlyRow[];
  selectedMonth: string;
  onEdit: (monthStr: string) => void;
  onDelete: (monthStr: string) => void;
}) {
  // Group by year
  const byYear = useMemo(() => {
    const grouped: Record<string, DrBoardMonthlyRow[]> = {};
    for (const row of rows) {
      const y = row.report_month.split("-")[0];
      if (!grouped[y]) grouped[y] = [];
      grouped[y].push(row);
    }
    return grouped;
  }, [rows]);

  const years = Object.keys(byYear).sort();

  return (
    <div className="bg-card rounded-xl shadow-sm border border-border overflow-hidden">
      <div className="px-4 py-3 bg-muted/40 border-b border-border">
        <h4 className="font-semibold text-sm">
          Wpisane dane ({rows.length}{" "}
          {rows.length === 1 ? "miesiąc" : "miesięcy"})
        </h4>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/30">
              <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground uppercase">
                Miesiąc
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-muted-foreground uppercase">
                Przychody
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-muted-foreground uppercase">
                Koszty kons.
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-muted-foreground uppercase">
                Marża
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-muted-foreground uppercase">
                Zysk
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-muted-foreground uppercase">
                Kons.
              </th>
              <th className="px-3 py-2.5 text-left text-xs font-medium text-muted-foreground uppercase">
                Placementy
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-muted-foreground uppercase">
                PLN/h
              </th>
              <th className="px-3 py-2.5 text-right text-xs font-medium text-muted-foreground uppercase">
                Hit %
              </th>
              <th className="px-3 py-2.5 text-center text-xs font-medium text-muted-foreground uppercase">
                Akcje
              </th>
            </tr>
          </thead>
          <tbody>
            {years.map((year) => {
              const yearRows = byYear[year];
              const sumRevenue = yearRows.reduce((s, r) => s + r.revenue, 0);
              const sumCosts = yearRows.reduce(
                (s, r) => s + r.consultant_costs,
                0,
              );
              const sumMargin = yearRows.reduce((s, r) => s + r.margin, 0);
              const sumProfit = yearRows.reduce((s, r) => s + r.profit, 0);
              const avgConsultants =
                yearRows.length > 0
                  ? Math.round(
                      yearRows.reduce((s, r) => s + r.active_consultants, 0) /
                        yearRows.length,
                    )
                  : 0;
              const sumPlacements = yearRows.reduce(
                (s, r) => s + r.placements,
                0,
              );
              const avgMarginH =
                yearRows.length > 0
                  ? yearRows.reduce((s, r) => s + r.avg_margin_per_hour, 0) /
                    yearRows.length
                  : 0;
              const avgHit =
                yearRows.length > 0
                  ? yearRows.reduce((s, r) => s + r.hit_ratio, 0) /
                    yearRows.length
                  : 0;

              return (
                <>
                  <tr key={`year-${year}`}>
                    <td
                      colSpan={10}
                      className="px-3 py-2 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-300 font-bold text-xs uppercase tracking-wider"
                    >
                      {year}
                    </td>
                  </tr>
                  {yearRows.map((row) => {
                    const isActive = row.report_month === selectedMonth;
                    const clientsText = formatClientsTooltip(
                      row.placement_clients,
                    );
                    return (
                      <tr
                        key={row.report_month}
                        className={`border-b border-border transition-colors ${
                          isActive
                            ? "bg-indigo-50 dark:bg-indigo-900/20"
                            : "hover:bg-muted/40"
                        }`}
                      >
                        <td
                          className={`px-3 py-2 font-medium ${isActive ? "text-indigo-700 dark:text-indigo-300" : ""}`}
                        >
                          {formatMonth(row.report_month)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {formatPLN(row.revenue)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {formatPLN(row.consultant_costs)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right tabular-nums font-medium ${row.margin >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
                        >
                          {formatPLN(row.margin)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right tabular-nums font-medium ${row.profit >= 0 ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
                        >
                          {formatPLN(row.profit)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {row.active_consultants}
                        </td>
                        <td className="px-3 py-2 text-left">
                          <span className="font-medium tabular-nums">
                            {row.placements}
                          </span>
                          {clientsText && (
                            <span
                              className="ml-1.5 text-xs text-muted-foreground"
                              title={clientsText}
                            >
                              (
                              {clientsText.length > 40
                                ? clientsText.slice(0, 40) + "…"
                                : clientsText}
                              )
                            </span>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {row.avg_margin_per_hour.toFixed(2)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {row.hit_ratio.toFixed(1)}%
                        </td>
                        <td className="px-3 py-2 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => onEdit(row.report_month)}
                              className="p-1.5 text-blue-600 hover:bg-blue-100 dark:hover:bg-blue-900/30 rounded-lg transition-colors"
                              title="Edytuj"
                              aria-label={`Edytuj ${formatMonth(row.report_month)}`}
                            >
                              <Edit2 className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => onDelete(row.report_month)}
                              className="p-1.5 text-red-600 hover:bg-red-100 dark:hover:bg-red-900/30 rounded-lg transition-colors"
                              title="Usuń"
                              aria-label={`Usuń ${formatMonth(row.report_month)}`}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  <tr
                    key={`sum-${year}`}
                    className="bg-indigo-50/60 dark:bg-indigo-900/10 border-b-2 border-indigo-200 dark:border-indigo-800"
                  >
                    <td className="px-3 py-2 font-bold text-xs text-indigo-700 dark:text-indigo-300 uppercase">
                      Suma {year}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-bold text-indigo-700 dark:text-indigo-300">
                      {formatPLN(sumRevenue)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-bold text-indigo-700 dark:text-indigo-300">
                      {formatPLN(sumCosts)}
                    </td>
                    <td
                      className={`px-3 py-2 text-right tabular-nums font-bold ${sumMargin >= 0 ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}`}
                    >
                      {formatPLN(sumMargin)}
                    </td>
                    <td
                      className={`px-3 py-2 text-right tabular-nums font-bold ${sumProfit >= 0 ? "text-green-700 dark:text-green-400" : "text-red-700 dark:text-red-400"}`}
                    >
                      {formatPLN(sumProfit)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-bold text-indigo-700 dark:text-indigo-300">
                      ø{avgConsultants}
                    </td>
                    <td className="px-3 py-2 text-left tabular-nums font-bold text-indigo-700 dark:text-indigo-300">
                      {sumPlacements}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-bold text-indigo-700 dark:text-indigo-300">
                      ø{avgMarginH.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums font-bold text-indigo-700 dark:text-indigo-300">
                      ø{avgHit.toFixed(1)}%
                    </td>
                    <td className="px-3 py-2"></td>
                  </tr>
                </>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
