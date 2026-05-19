"use client";

/**
 * Body Leasing Data Entry — admin form do wpisywania tygodniowych KPI per user.
 *
 * Port `BodyLeasingDataEntry.tsx` z artur-t-96/InfraReporter (835 linii).
 *
 * Funkcje (DR parity):
 * - Filter po week (date picker — pon. wybranego tygodnia)
 * - Role filter: All / Sourcer / TAC
 * - "Wypełnij wszystkich" — auto-add rows dla wszystkich userów (zachowuje
 *   istniejące wpisy, dodaje brakujących)
 * - Inline edit verifications/recommendations/interviews/placements/days/LinkedIn
 * - "Zastosuj do wszystkich" — bulk days_worked update
 * - Per-row Save lub bulk "Zapisz wszystkie (N)"
 * - Zero-value yellow highlight (oznacza brakujące dane)
 * - Summary cards: sumy weryfikacji/rekomendacji/interviews/placements
 * - LinkedIn columns visible tylko dla TAC/recruiter
 */

import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Save,
  RefreshCw,
  Calendar,
  AlertCircle,
  CheckCircle,
  Building2,
  Plus,
  Trash2,
  Filter,
} from "lucide-react";
import {
  dynareporterBodyLeasingApi,
  dynareporterAdminUsersApi,
  type DrKpiBodyLeasingEntry,
  type DrEmployeeRow,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

/**
 * Helper: ISO week number from a Date.
 */
function getIsoWeek(d: Date): number {
  const t = new Date(d.getTime());
  t.setHours(0, 0, 0, 0);
  t.setDate(t.getDate() + 4 - (t.getDay() || 7));
  const yearStart = new Date(t.getFullYear(), 0, 1);
  return Math.ceil(((t.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

function getWeekStart(date: Date): Date {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(d.setDate(diff));
}

function getWeekEnd(date: Date): Date {
  const start = getWeekStart(date);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  return end;
}

function formatDateInput(d: Date): string {
  return d.toISOString().split("T")[0];
}

function formatWeekRange(weekStart: string): string {
  const start = new Date(weekStart);
  const end = getWeekEnd(start);
  return `${start.toLocaleDateString("pl-PL")} – ${end.toLocaleDateString("pl-PL")}`;
}

type RoleFilter = "all" | "sourcer" | "tac";

type EditableRow = {
  user_id: number;
  user_name: string;
  user_email: string;
  user_role: string;
  verifications: number;
  recommendations: number;
  interviews: number;
  placements: number;
  requests: number;
  days_worked: number;
  linkedin_cv_added: number;
  linkedin_messages_sent: number;
  linkedin_responses_received: number;
  existing_entry_id: number | null; // jeśli null = nowy wpis
  dirty: boolean;
};

function highlightZeroClass(value: number): string {
  return value === 0
    ? "bg-yellow-50 dark:bg-yellow-900/20 border-yellow-300 dark:border-yellow-600"
    : "bg-background border-input";
}

const ALLOWED_DATA_ENTRY_ROLES = ["sourcer", "tac", "recruiter"];

export function BodyLeasingDataEntry() {
  const queryClient = useQueryClient();
  const [weekStartDate, setWeekStartDate] = useState<string>(() => {
    const today = new Date();
    return formatDateInput(getWeekStart(today));
  });
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [rows, setRows] = useState<EditableRow[]>([]);
  const [bulkDaysWorked, setBulkDaysWorked] = useState<string>("");
  const [saveStatus, setSaveStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  // Fetch existing entries for the target week
  const entriesQuery = useQuery({
    queryKey: ["dr-bl-admin-entries", weekStartDate],
    queryFn: () =>
      dynareporterBodyLeasingApi.allEntries({
        from_date: weekStartDate,
        to_date: weekStartDate,
      }),
    staleTime: 30_000,
  });

  // Fetch all employees (dla "Wypełnij wszystkich" + dla user dropdown)
  const employeesQuery = useQuery({
    queryKey: ["dr-employees"],
    queryFn: () => dynareporterAdminUsersApi.employees(),
    staleTime: 5 * 60_000,
  });

  // Filtered users — only data-entry roles + active + matching role filter
  const filteredUsers = useMemo(() => {
    const all = employeesQuery.data ?? [];
    return all
      .filter((u: DrEmployeeRow) => {
        if (!u.is_active) return false;
        if (!ALLOWED_DATA_ENTRY_ROLES.includes(u.role)) return false;
        if (roleFilter === "all") return true;
        return u.role === roleFilter;
      })
      .sort((a, b) => (a.name ?? "").localeCompare(b.name ?? "", "pl"));
  }, [employeesQuery.data, roleFilter]);

  // Build editable rows on entries load — keep only matching role filter.
  useEffect(() => {
    if (!entriesQuery.data || !employeesQuery.data) return;
    const userById = new Map(employeesQuery.data.map((u) => [u.id, u]));
    const built: EditableRow[] = entriesQuery.data
      .map((e: DrKpiBodyLeasingEntry) => {
        const u = userById.get(e.user_id);
        if (!u) return null;
        return {
          user_id: e.user_id,
          user_name: e.user_name ?? u.name ?? "",
          user_email: e.user_email ?? u.email ?? "",
          user_role: u.role,
          verifications: e.verifications ?? 0,
          recommendations: e.recommendations ?? 0,
          interviews: e.interviews ?? 0,
          placements: e.placements ?? 0,
          requests: e.requests ?? 0,
          days_worked: e.days_worked ?? 5,
          linkedin_cv_added: e.linkedin_cv_added ?? 0,
          linkedin_messages_sent: e.linkedin_messages_sent ?? 0,
          linkedin_responses_received: e.linkedin_responses_received ?? 0,
          existing_entry_id: e.id,
          dirty: false,
        } as EditableRow;
      })
      .filter((r): r is EditableRow => r !== null);
    setRows(built);
  }, [entriesQuery.data, employeesQuery.data]);

  // Filter visible rows by role
  const visibleRows = useMemo(() => {
    if (roleFilter === "all") return rows;
    return rows.filter((r) => r.user_role === roleFilter);
  }, [rows, roleFilter]);

  const upsertMutation = useMutation({
    mutationFn: (row: EditableRow) =>
      dynareporterBodyLeasingApi.upsert({
        user_id: row.user_id,
        report_date: weekStartDate,
        week_number: getIsoWeek(new Date(weekStartDate)),
        verifications: row.verifications,
        recommendations: row.recommendations,
        interviews: row.interviews,
        placements: row.placements,
        requests: row.requests,
        days_worked: row.days_worked,
        linkedin_cv_added: row.linkedin_cv_added,
        linkedin_messages_sent: row.linkedin_messages_sent,
        linkedin_responses_received: row.linkedin_responses_received,
        is_draft: false,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-bl-admin-entries"] });
      queryClient.invalidateQueries({ queryKey: ["dr-rekrutacja-dashboard"] });
    },
  });

  const handleCellChange = (
    user_id: number,
    field: keyof Omit<
      EditableRow,
      "user_id" | "user_name" | "user_email" | "user_role" | "existing_entry_id" | "dirty"
    >,
    value: number,
  ) => {
    setRows((prev) =>
      prev.map((r) =>
        r.user_id === user_id ? { ...r, [field]: value, dirty: true } : r,
      ),
    );
  };

  const handleSaveRow = async (row: EditableRow) => {
    try {
      await upsertMutation.mutateAsync(row);
      setRows((prev) =>
        prev.map((r) => (r.user_id === row.user_id ? { ...r, dirty: false } : r)),
      );
      setSaveStatus({ type: "success", message: `Zapisano ${row.user_name}` });
      setTimeout(() => setSaveStatus(null), 3000);
    } catch (e: unknown) {
      setSaveStatus({ type: "error", message: `Błąd: ${extractErrorMsg(e)}` });
    }
  };

  const handleSaveAll = async () => {
    const dirtyRows = rows.filter((r) => r.dirty);
    if (dirtyRows.length === 0) return;
    const savedUserIds = new Set<number>();
    let failCount = 0;
    for (const row of dirtyRows) {
      try {
        await upsertMutation.mutateAsync(row);
        savedUserIds.add(row.user_id);
      } catch {
        failCount++;
      }
    }
    setRows((prev) =>
      prev.map((r) =>
        savedUserIds.has(r.user_id) ? { ...r, dirty: false } : r,
      ),
    );
    setSaveStatus({
      type: failCount === 0 ? "success" : "error",
      message: `Zapisano ${savedUserIds.size}/${dirtyRows.length}${failCount > 0 ? ` (${failCount} błędów)` : ""}`,
    });
    setTimeout(() => setSaveStatus(null), 5000);
  };

  /**
   * "Wypełnij wszystkich" — dodaj wiersz dla każdego usera spełniającego filter
   * jeśli już go nie ma na liście. Istniejące wiersze zostają nienaruszone.
   */
  const handleFillAllUsers = () => {
    const existingUserIds = new Set(rows.map((r) => r.user_id));
    const newRows: EditableRow[] = filteredUsers
      .filter((u: DrEmployeeRow) => !existingUserIds.has(u.id))
      .map((u: DrEmployeeRow) => ({
        user_id: u.id,
        user_name: u.name ?? `${u.first_name ?? ""} ${u.last_name ?? ""}`.trim(),
        user_email: u.email,
        user_role: u.role,
        verifications: 0,
        recommendations: 0,
        interviews: 0,
        placements: 0,
        requests: 0,
        days_worked: 5,
        linkedin_cv_added: 0,
        linkedin_messages_sent: 0,
        linkedin_responses_received: 0,
        existing_entry_id: null,
        dirty: true, // mark as dirty by default — admin musi kliknąć Save
      }));
    if (newRows.length === 0) {
      setSaveStatus({
        type: "success",
        message: "Wszyscy userzy już mają wiersze.",
      });
      setTimeout(() => setSaveStatus(null), 3000);
      return;
    }
    setRows((prev) => [...prev, ...newRows]);
    setSaveStatus({
      type: "success",
      message: `Dodano ${newRows.length} wierszy. Kliknij "Zapisz wszystkie" po wprowadzeniu danych.`,
    });
    setTimeout(() => setSaveStatus(null), 5000);
  };

  /** Bulk apply days_worked to all visible rows. */
  const handleBulkDaysWorked = () => {
    const n = Number(bulkDaysWorked);
    if (!Number.isFinite(n) || n < 0 || n > 7) return;
    const visibleIds = new Set(visibleRows.map((r) => r.user_id));
    setRows((prev) =>
      prev.map((r) =>
        visibleIds.has(r.user_id)
          ? { ...r, days_worked: n, dirty: true }
          : r,
      ),
    );
    setSaveStatus({
      type: "success",
      message: `Ustawiono dni pracy = ${n} dla ${visibleIds.size} wierszy. Kliknij "Zapisz wszystkie" by zapisać.`,
    });
    setTimeout(() => setSaveStatus(null), 5000);
  };

  /** Remove row from local state (does NOT delete from DB if existing_entry_id). */
  const handleRemoveRow = (user_id: number) => {
    setRows((prev) => prev.filter((r) => r.user_id !== user_id));
  };

  const dirtyCount = rows.filter((r) => r.dirty).length;

  // Summary totals (visible rows only — match what user sees)
  const summary = useMemo(() => {
    return visibleRows.reduce(
      (acc, r) => ({
        verifications: acc.verifications + (r.verifications || 0),
        recommendations: acc.recommendations + (r.recommendations || 0),
        interviews: acc.interviews + (r.interviews || 0),
        placements: acc.placements + (r.placements || 0),
      }),
      { verifications: 0, recommendations: 0, interviews: 0, placements: 0 },
    );
  }, [visibleRows]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Building2 className="w-5 h-5 text-blue-600" />
              <h3 className="text-lg font-semibold">
                Rekrutacja — wpisywanie tygodniowych KPI
              </h3>
            </div>

            <div className="flex items-center gap-2 ml-auto flex-wrap">
              {/* Date picker */}
              <Calendar className="w-4 h-4 text-muted-foreground" />
              <label className="text-sm text-muted-foreground">Tydzień (pon):</label>
              <input
                type="date"
                value={weekStartDate}
                onChange={(e) => setWeekStartDate(e.target.value)}
                className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                aria-label="Wybierz datę poniedziałku tygodnia"
              />
              <span className="text-xs text-muted-foreground">
                {formatWeekRange(weekStartDate)}
              </span>

              {/* Role filter */}
              <Filter className="w-4 h-4 text-muted-foreground ml-2" />
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value as RoleFilter)}
                className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                aria-label="Filtruj po roli"
              >
                <option value="all">Wszyscy</option>
                <option value="sourcer">Sourcer</option>
                <option value="tac">TAC</option>
              </select>

              <Button
                variant="outline"
                size="sm"
                onClick={() => entriesQuery.refetch()}
                aria-label="Odśwież listę"
              >
                <RefreshCw className="w-4 h-4" aria-hidden="true" />
              </Button>
            </div>
          </div>

          {/* Action row: Wypełnij wszystkich + Zapisz wszystkie */}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={handleFillAllUsers}
              disabled={employeesQuery.isLoading || !employeesQuery.data}
            >
              <Plus className="w-4 h-4" aria-hidden="true" />
              <span className="ml-1">Wypełnij wszystkich</span>
            </Button>
            {dirtyCount > 0 && (
              <Button size="sm" onClick={handleSaveAll} disabled={upsertMutation.isPending}>
                <Save className="w-4 h-4" aria-hidden="true" />
                <span className="ml-1">Zapisz wszystkie ({dirtyCount})</span>
              </Button>
            )}
          </div>

          {saveStatus && (
            <div
              className={`mt-3 flex items-center gap-2 text-sm ${
                saveStatus.type === "success" ? "text-emerald-600" : "text-rose-600"
              }`}
            >
              {saveStatus.type === "success" ? (
                <CheckCircle className="w-4 h-4" aria-hidden="true" />
              ) : (
                <AlertCircle className="w-4 h-4" aria-hidden="true" />
              )}
              {saveStatus.message}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Bulk apply days_worked */}
      {visibleRows.length > 0 && (
        <Card className="bg-blue-50/50 dark:bg-blue-950/10 border-blue-200 dark:border-blue-800">
          <CardContent className="pt-4 pb-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm font-medium text-blue-900 dark:text-blue-100">
                Zastosuj do wszystkich:
              </span>
              <div className="flex items-center gap-2">
                <label className="text-sm text-blue-800 dark:text-blue-200">
                  Dni pracy:
                </label>
                <input
                  type="number"
                  min={0}
                  max={7}
                  placeholder="5"
                  value={bulkDaysWorked}
                  onChange={(e) => setBulkDaysWorked(e.target.value)}
                  className="px-2 py-1 text-sm bg-background border border-blue-300 dark:border-blue-700 rounded w-20"
                  aria-label="Liczba dni roboczych dla wszystkich wierszy"
                />
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleBulkDaysWorked}
                  disabled={!bulkDaysWorked}
                >
                  Zastosuj
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Data Entry Table */}
      <Card>
        <CardContent className="pt-6">
          {entriesQuery.isLoading || employeesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              Ładowanie…
            </p>
          ) : entriesQuery.error ? (
            <p className="text-sm text-destructive py-6 text-center">
              Błąd ładowania wpisów: {String(entriesQuery.error)}
            </p>
          ) : visibleRows.length === 0 ? (
            <div className="py-12 text-center space-y-2">
              <AlertCircle className="w-8 h-8 text-muted-foreground mx-auto" />
              <p className="text-sm text-muted-foreground">
                Brak wpisów dla tygodnia od {weekStartDate}.
              </p>
              <p className="text-xs text-muted-foreground">
                Kliknij <strong>Wypełnij wszystkich</strong> aby dodać wiersze
                dla wszystkich userów + wprowadź dane + zapisz.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-muted/40">
                  <tr>
                    <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Osoba
                    </th>
                    <th className="px-2 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Rola
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Wer.
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Rek.
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Int.
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Plac.
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Req.
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Dni
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase text-blue-600 dark:text-blue-400">
                      LI CV
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase text-blue-600 dark:text-blue-400">
                      LI msg
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase text-blue-600 dark:text-blue-400">
                      LI resp
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Akcje
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {visibleRows.map((row) => {
                    const hasLinkedin =
                      row.user_role === "tac" || row.user_role === "recruiter";
                    const isNew = row.existing_entry_id === null;
                    return (
                      <tr
                        key={row.user_id}
                        className={`${row.dirty ? "bg-amber-50/30 dark:bg-amber-950/10" : ""} ${isNew ? "italic" : ""}`}
                      >
                        <td className="px-2 py-1.5 text-sm font-medium">
                          {row.user_name}
                          {isNew && (
                            <span className="ml-2 inline-block px-1.5 py-0.5 text-[9px] font-semibold bg-emerald-200 dark:bg-emerald-800 text-emerald-900 dark:text-emerald-100 rounded">
                              NOWY
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-1.5 text-xs text-muted-foreground uppercase">
                          {row.user_role === "tac"
                            ? "TAC"
                            : row.user_role === "sourcer"
                              ? "Sourcer"
                              : row.user_role}
                        </td>
                        {(
                          [
                            "verifications",
                            "recommendations",
                            "interviews",
                            "placements",
                            "requests",
                            "days_worked",
                          ] as const
                        ).map((field) => (
                          <td key={field} className="px-1 py-1">
                            <input
                              type="number"
                              min={0}
                              max={field === "days_worked" ? 7 : undefined}
                              value={row[field]}
                              onChange={(e) =>
                                handleCellChange(
                                  row.user_id,
                                  field,
                                  Number(e.target.value),
                                )
                              }
                              aria-label={`${field} dla ${row.user_name}`}
                              className={`w-16 text-center text-sm tabular-nums rounded border px-1 py-0.5 ${highlightZeroClass(row[field])}`}
                            />
                          </td>
                        ))}
                        {(
                          [
                            "linkedin_cv_added",
                            "linkedin_messages_sent",
                            "linkedin_responses_received",
                          ] as const
                        ).map((field) => (
                          <td key={field} className="px-1 py-1">
                            {hasLinkedin ? (
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
                                className={`w-16 text-center text-sm tabular-nums rounded border px-1 py-0.5 ${highlightZeroClass(row[field])}`}
                              />
                            ) : (
                              <span className="block text-center text-muted-foreground">
                                —
                              </span>
                            )}
                          </td>
                        ))}
                        <td className="px-2 py-1 text-center">
                          <div className="flex items-center justify-center gap-1">
                            <Button
                              size="sm"
                              variant={row.dirty ? "primary" : "outline"}
                              onClick={() => handleSaveRow(row)}
                              disabled={!row.dirty || upsertMutation.isPending}
                              aria-label={`Zapisz wpis dla ${row.user_name}`}
                            >
                              <Save className="w-3.5 h-3.5" aria-hidden="true" />
                            </Button>
                            {isNew && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleRemoveRow(row.user_id)}
                                aria-label={`Usuń wiersz ${row.user_name}`}
                              >
                                <Trash2 className="w-3.5 h-3.5 text-rose-600" />
                              </Button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Summary totals (z DR original) */}
      {visibleRows.length > 0 && (
        <Card className="bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-950/20 dark:to-indigo-950/20 border-blue-200 dark:border-blue-800">
          <CardContent className="pt-4 pb-4">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <span className="text-sm font-medium text-blue-800 dark:text-blue-200">
                Podsumowanie ({visibleRows.length}{" "}
                {visibleRows.length === 1 ? "wiersz" : "wierszy"})
              </span>
              {dirtyCount > 0 && (
                <span className="text-xs text-amber-700 dark:text-amber-400">
                  {dirtyCount} niezapisanych zmian
                </span>
              )}
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="bg-background/60 dark:bg-background/30 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold tabular-nums text-blue-700 dark:text-blue-400">
                  {summary.verifications}
                </div>
                <div className="text-xs text-blue-600 dark:text-blue-300 font-medium uppercase">
                  Weryfikacje
                </div>
              </div>
              <div className="bg-background/60 dark:bg-background/30 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold tabular-nums text-purple-700 dark:text-purple-400">
                  {summary.recommendations}
                </div>
                <div className="text-xs text-purple-600 dark:text-purple-300 font-medium uppercase">
                  Rekomendacje
                </div>
              </div>
              <div className="bg-background/60 dark:bg-background/30 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold tabular-nums text-orange-700 dark:text-orange-400">
                  {summary.interviews}
                </div>
                <div className="text-xs text-orange-600 dark:text-orange-300 font-medium uppercase">
                  Interviews
                </div>
              </div>
              <div className="bg-background/60 dark:bg-background/30 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold tabular-nums text-emerald-700 dark:text-emerald-400">
                  {summary.placements}
                </div>
                <div className="text-xs text-emerald-600 dark:text-emerald-300 font-medium uppercase">
                  Placements
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
