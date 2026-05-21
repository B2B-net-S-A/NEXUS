"use client";

/**
 * Delivery Lead Data Entry — admin formularz miesięcznych KPI dla DL.
 *
 * Port `DeliveryLeadDataEntry.tsx` z artur-t-96/InfraReporter (419 linii).
 *
 * Funkcje (DR parity):
 * - Year + Month picker
 * - "Wypełnij wszystkich" — auto-add wiersze dla wszystkich aktywnych DLs,
 *   pre-fill istniejące wartości z bazy
 * - Per-row inline edit (requests/vacancies/placements/open_requests/open_vacancies)
 * - Team stats summary (hit ratio + fill rate + sumy)
 * - Per-row Save lub bulk "Zapisz wszystkie (N dirty)"
 */

import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Save,
  RefreshCw,
  Target,
  CheckCircle,
  AlertCircle,
  Plus,
  TrendingUp,
} from "lucide-react";
import {
  dynareporterDeliveryLeadApi,
  type DrDLMember,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DeliveryLeadBrowse } from "./DeliveryLeadBrowse";
import { DataHistoryView } from "./DataHistoryView";

type AdminTab = "entry" | "browse" | "history";

const MONTH_NAMES_PL = [
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

const HIT_RATIO_TARGET = 30;

type DLRow = {
  user_id: number;
  user_name: string;
  is_active: boolean;
  requests: number;
  vacancies: number;
  placements: number;
  open_requests: number;
  open_vacancies: number;
  has_existing: boolean;
  dirty: boolean;
};

export function DeliveryLeadDataEntry() {
  const queryClient = useQueryClient();
  const now = new Date();
  const [tab, setTab] = useState<AdminTab>("entry");
  const [selectedYear, setSelectedYear] = useState(now.getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(now.getMonth() + 1);
  const [rows, setRows] = useState<DLRow[]>([]);
  const [saveStatus, setSaveStatus] = useState<{
    type: "success" | "error";
    msg: string;
  } | null>(null);

  const reportMonth = `${selectedYear}-${String(selectedMonth).padStart(2, "0")}`;
  const monthStart = `${reportMonth}-01`;
  const monthEnd = new Date(selectedYear, selectedMonth, 0)
    .toISOString()
    .slice(0, 10);

  // Get list of all DLs (all-time aggregates for the user-name lookup).
  const allTimeQuery = useQuery({
    queryKey: ["dr-dl-dashboard-admin-alltime"],
    queryFn: () => dynareporterDeliveryLeadApi.dashboard(),
    staleTime: 60_000,
  });

  // Get month-specific snapshot for pre-filling existing values.
  const monthQuery = useQuery({
    queryKey: ["dr-dl-month-snapshot-admin", monthStart, monthEnd],
    queryFn: () =>
      dynareporterDeliveryLeadApi.dashboard({
        start_date: monthStart,
        end_date: monthEnd,
      }),
    staleTime: 30_000,
  });

  const yearOptions = useMemo(() => {
    const base = now.getFullYear();
    return [base - 2, base - 1, base, base + 1];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * "Wypełnij wszystkich" — automatycznie buduje rows dla wszystkich aktywnych
   * DLs, z pre-fill z monthQuery snapshot (istniejące wartości) lub zerami.
   */
  const handleFillAll = () => {
    if (!allTimeQuery.data) return;
    const monthSnapshotById = new Map(
      (monthQuery.data?.delivery_leads ?? []).map((dl: DrDLMember) => [
        dl.id,
        dl,
      ]),
    );
    const allActiveDls = allTimeQuery.data.delivery_leads.filter(
      (dl: DrDLMember) => dl.is_active,
    );
    const newRows: DLRow[] = allActiveDls.map((dl: DrDLMember) => {
      const monthData = monthSnapshotById.get(dl.id);
      // Use month-specific data if available (existing entry), otherwise zeros.
      const hasMonthData = monthData && monthData.requests + monthData.placements > 0;
      return {
        user_id: dl.id,
        user_name: dl.name,
        is_active: dl.is_active,
        requests: monthData?.requests ?? 0,
        vacancies: monthData?.vacancies ?? 0,
        placements: monthData?.placements ?? 0,
        open_requests: monthData?.open_requests ?? 0,
        open_vacancies: monthData?.open_vacancies ?? 0,
        has_existing: !!hasMonthData,
        dirty: false,
      };
    });
    setRows(newRows);
    setSaveStatus({
      type: "success",
      msg: `Załadowano ${newRows.length} DL (${newRows.filter((r) => r.has_existing).length} z danymi)`,
    });
    setTimeout(() => setSaveStatus(null), 5000);
  };

  // Auto-fill on month change (if already loaded once)
  useEffect(() => {
    if (allTimeQuery.data && monthQuery.data && rows.length > 0) {
      handleFillAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportMonth, monthQuery.data]);

  const upsertMutation = useMutation({
    mutationFn: (row: DLRow) =>
      dynareporterDeliveryLeadApi.upsert({
        user_id: row.user_id,
        report_month: reportMonth,
        requests: row.requests,
        placements: row.placements,
        vacancies: row.vacancies,
        open_requests: row.open_requests,
        open_vacancies: row.open_vacancies,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-dl-dashboard"] });
      queryClient.invalidateQueries({ queryKey: ["dr-dl-month-snapshot-admin"] });
    },
  });

  const handleCellChange = (
    user_id: number,
    field: keyof Omit<
      DLRow,
      "user_id" | "user_name" | "is_active" | "has_existing" | "dirty"
    >,
    value: number,
  ) => {
    setRows((prev) =>
      prev.map((r) =>
        r.user_id === user_id ? { ...r, [field]: value, dirty: true } : r,
      ),
    );
  };

  const handleSaveRow = async (row: DLRow) => {
    try {
      await upsertMutation.mutateAsync(row);
      setRows((prev) =>
        prev.map((r) =>
          r.user_id === row.user_id ? { ...r, dirty: false, has_existing: true } : r,
        ),
      );
      setSaveStatus({ type: "success", msg: `Zapisano ${row.user_name}` });
      setTimeout(() => setSaveStatus(null), 3000);
    } catch (e: unknown) {
      setSaveStatus({ type: "error", msg: `Błąd: ${extractErrorMsg(e)}` });
    }
  };

  const handleSaveAll = async () => {
    const dirtyRows = rows.filter((r) => r.dirty);
    if (dirtyRows.length === 0) return;
    const savedIds = new Set<number>();
    let failCount = 0;
    for (const row of dirtyRows) {
      try {
        await upsertMutation.mutateAsync(row);
        savedIds.add(row.user_id);
      } catch {
        failCount++;
      }
    }
    setRows((prev) =>
      prev.map((r) =>
        savedIds.has(r.user_id)
          ? { ...r, dirty: false, has_existing: true }
          : r,
      ),
    );
    setSaveStatus({
      type: failCount === 0 ? "success" : "error",
      msg: `Zapisano ${savedIds.size}/${dirtyRows.length}${failCount > 0 ? ` (${failCount} błędów)` : ""}`,
    });
    setTimeout(() => setSaveStatus(null), 5000);
  };

  const dirtyCount = rows.filter((r) => r.dirty).length;

  // Team stats summary (mirror DR original)
  const teamStats = useMemo(() => {
    const totals = rows.reduce(
      (acc, r) => ({
        requests: acc.requests + r.requests,
        placements: acc.placements + r.placements,
        vacancies: acc.vacancies + r.vacancies,
        open_requests: acc.open_requests + r.open_requests,
        open_vacancies: acc.open_vacancies + r.open_vacancies,
      }),
      {
        requests: 0,
        placements: 0,
        vacancies: 0,
        open_requests: 0,
        open_vacancies: 0,
      },
    );
    return {
      ...totals,
      hitRatio:
        totals.requests > 0
          ? Math.round((totals.placements / totals.requests) * 1000) / 10
          : 0,
      fillRate:
        totals.vacancies > 0
          ? Math.round((totals.placements / totals.vacancies) * 1000) / 10
          : 0,
    };
  }, [rows]);

  return (
    <div className="space-y-4">
      {/* Zakładki: Wprowadzanie danych / Przeglądaj dane / Historia */}
      <div className="flex gap-1 border-b border-border">
        {(
          [
            ["entry", "Wprowadzanie danych"],
            ["browse", "Przeglądaj dane"],
            ["history", "Historia"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "browse" && <DeliveryLeadBrowse />}
      {tab === "history" && (
        <DataHistoryView
          tableName="kpi_delivery_lead"
          uploadFileType="delivery-lead"
          title="Historia zmian — Delivery Lead"
        />
      )}

      {tab === "entry" && (
        <>
      <Card>
        <CardContent className="pt-6">
          <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
            <Target className="w-5 h-5 text-orange-600" />
            Delivery Lead — wpisywanie miesięcznych KPI
          </h3>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label className="text-sm text-muted-foreground">Miesiąc:</label>
              <select
                value={selectedMonth}
                onChange={(e) => setSelectedMonth(Number(e.target.value))}
                className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                aria-label="Wybierz miesiąc"
              >
                {MONTH_NAMES_PL.map((name, i) => (
                  <option key={i + 1} value={i + 1}>
                    {name}
                  </option>
                ))}
              </select>
              <select
                value={selectedYear}
                onChange={(e) => setSelectedYear(Number(e.target.value))}
                className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                aria-label="Wybierz rok"
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>

            <Button
              size="sm"
              variant="outline"
              onClick={handleFillAll}
              disabled={allTimeQuery.isLoading || !allTimeQuery.data}
              className="ml-auto"
            >
              <Plus className="w-4 h-4" aria-hidden="true" />
              <span className="ml-1">Wypełnij wszystkich</span>
            </Button>
            {dirtyCount > 0 && (
              <Button
                size="sm"
                onClick={handleSaveAll}
                disabled={upsertMutation.isPending}
              >
                <Save className="w-4 h-4" aria-hidden="true" />
                <span className="ml-1">Zapisz wszystkie ({dirtyCount})</span>
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                allTimeQuery.refetch();
                monthQuery.refetch();
              }}
              aria-label="Odśwież listę"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
            </Button>
          </div>

          {saveStatus && (
            <div
              className={`mt-3 flex items-center gap-2 text-sm ${
                saveStatus.type === "success"
                  ? "text-emerald-600"
                  : "text-rose-600"
              }`}
            >
              {saveStatus.type === "success" ? (
                <CheckCircle className="w-4 h-4" aria-hidden="true" />
              ) : (
                <AlertCircle className="w-4 h-4" aria-hidden="true" />
              )}
              {saveStatus.msg}
            </div>
          )}
        </CardContent>
      </Card>

      {rows.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center space-y-2">
            <AlertCircle className="w-8 h-8 text-muted-foreground mx-auto" />
            <p className="text-sm text-muted-foreground">
              Kliknij <strong>Wypełnij wszystkich</strong> aby załadować
              listę DL na {MONTH_NAMES_PL[selectedMonth - 1]} {selectedYear}.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* DLs Table */}
          <Card>
            <CardContent className="pt-6">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Delivery Lead
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Requests
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Vacancies
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Placements
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Open req.
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Open vac.
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Hit ratio
                      </th>
                      <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                        Akcja
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {rows.map((row) => {
                      const hitRatio =
                        row.requests > 0
                          ? Math.round((row.placements / row.requests) * 1000) / 10
                          : 0;
                      return (
                        <tr
                          key={row.user_id}
                          className={`${row.dirty ? "bg-amber-50/30 dark:bg-amber-950/10" : ""}`}
                        >
                          <td className="px-2 py-1.5 text-sm font-medium">
                            {row.user_name}
                            {!row.has_existing && (
                              <span className="ml-2 inline-block px-1.5 py-0.5 text-[9px] font-semibold bg-emerald-200 dark:bg-emerald-800 text-emerald-900 dark:text-emerald-100 rounded">
                                NOWY
                              </span>
                            )}
                          </td>
                          {(
                            [
                              "requests",
                              "vacancies",
                              "placements",
                              "open_requests",
                              "open_vacancies",
                            ] as const
                          ).map((field) => (
                            <td key={field} className="px-1 py-1">
                              <input
                                type="number"
                                min={0}
                                value={row[field]}
                                onChange={(e) =>
                                  handleCellChange(
                                    row.user_id,
                                    field,
                                    Number(e.target.value),
                                  )
                                }
                                aria-label={`${field} dla ${row.user_name}`}
                                className="w-20 text-center text-sm tabular-nums rounded border border-input bg-background px-1 py-0.5"
                              />
                            </td>
                          ))}
                          <td className="px-2 py-1.5 text-center text-sm tabular-nums">
                            <span
                              className={
                                hitRatio >= HIT_RATIO_TARGET
                                  ? "text-emerald-600 font-semibold"
                                  : "text-muted-foreground"
                              }
                            >
                              {hitRatio}%
                            </span>
                          </td>
                          <td className="px-2 py-1 text-center">
                            <Button
                              size="sm"
                              variant={row.dirty ? "primary" : "outline"}
                              onClick={() => handleSaveRow(row)}
                              disabled={!row.dirty || upsertMutation.isPending}
                              aria-label={`Zapisz wpis dla ${row.user_name}`}
                            >
                              <Save className="w-3.5 h-3.5" aria-hidden="true" />
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* Team summary stats */}
          <Card className="bg-gradient-to-r from-orange-50 to-amber-50 dark:from-orange-950/20 dark:to-amber-950/20 border-orange-200 dark:border-orange-800">
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-2 mb-3">
                <TrendingUp className="w-4 h-4 text-orange-600" />
                <span className="text-sm font-medium text-orange-800 dark:text-orange-200">
                  Statystyki zespołu DL — {MONTH_NAMES_PL[selectedMonth - 1]}{" "}
                  {selectedYear}
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
                <StatCard label="Requests" value={teamStats.requests} />
                <StatCard label="Vacancies" value={teamStats.vacancies} />
                <StatCard label="Placements" value={teamStats.placements} accent />
                <StatCard
                  label="Open req."
                  value={teamStats.open_requests}
                />
                <StatCard
                  label="Open vac."
                  value={teamStats.open_vacancies}
                />
                <StatCard
                  label="Hit Ratio"
                  value={`${teamStats.hitRatio}%`}
                  accent={teamStats.hitRatio >= HIT_RATIO_TARGET}
                  hint={`target ${HIT_RATIO_TARGET}%`}
                />
                <StatCard
                  label="Fill Rate"
                  value={`${teamStats.fillRate}%`}
                />
              </div>
            </CardContent>
          </Card>
        </>
      )}
        </>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  accent,
  hint,
}: {
  label: string;
  value: number | string;
  accent?: boolean;
  hint?: string;
}) {
  return (
    <div className="bg-background/60 dark:bg-background/30 rounded-lg p-3 text-center">
      <div
        className={`text-2xl font-bold tabular-nums ${accent ? "text-emerald-700 dark:text-emerald-400" : "text-orange-700 dark:text-orange-400"}`}
      >
        {value}
      </div>
      <div className="text-xs text-muted-foreground font-medium uppercase">
        {label}
      </div>
      {hint && (
        <div className="text-[10px] text-muted-foreground italic">{hint}</div>
      )}
    </div>
  );
}
