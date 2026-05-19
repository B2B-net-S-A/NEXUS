"use client";

/**
 * Body Leasing Data Entry — admin form do wpisywania tygodniowych KPI per user.
 *
 * Port `BodyLeasingDataEntry.tsx` z artur-t-96/InfraReporter.
 *
 * Funkcje:
 * - Filter po week (date picker)
 * - Lista wszystkich userów + ich aktualnych wpisów dla wybranego tygodnia
 * - Inline edit verifications/recommendations/interviews/placements
 * - Save button → POST `/api/dynareporter/kpi/body-leasing?user_id=X` z payload
 * - Yellow highlight dla pustych pól (value=0)
 */

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Save, RefreshCw, Calendar, AlertCircle, CheckCircle, Building2 } from "lucide-react";
import { dynareporterBodyLeasingApi, type DrKpiBodyLeasingEntry } from "@/lib/api";
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

function formatDateInput(d: Date): string {
  return d.toISOString().split("T")[0];
}

type EditableRow = {
  user_id: number;
  user_name: string;
  user_email: string;
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

export function BodyLeasingDataEntry() {
  const queryClient = useQueryClient();
  // Default to current week's Monday
  const [weekStartDate, setWeekStartDate] = useState<string>(() => {
    const today = new Date();
    return formatDateInput(getWeekStart(today));
  });
  const [rows, setRows] = useState<EditableRow[]>([]);
  const [saveStatus, setSaveStatus] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  // Fetch all entries for the target week
  const entriesQuery = useQuery({
    queryKey: ["dr-bl-admin-entries", weekStartDate],
    queryFn: () =>
      dynareporterBodyLeasingApi.allEntries({
        from_date: weekStartDate,
        to_date: weekStartDate,
      }),
    staleTime: 30_000,
  });

  // Build editable rows from entries on data load.
  // `useEffect` (not `useMemo`) — setRows is a side-effect, useMemo is for pure
  // computation. Under React 19 concurrent rendering, useMemo with setState
  // produces undefined behavior (double-render, missed updates).
  useEffect(() => {
    if (entriesQuery.data) {
      setRows(
        entriesQuery.data.map((e: DrKpiBodyLeasingEntry) => ({
          user_id: e.user_id,
          user_name: e.user_name ?? "",
          user_email: e.user_email ?? "",
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
        })),
      );
    }
  }, [entriesQuery.data]);

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
    field: keyof Omit<EditableRow, "user_id" | "user_name" | "user_email" | "existing_entry_id" | "dirty">,
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
      const errMsg = e instanceof Error ? e.message : String(e);
      setSaveStatus({ type: "error", message: `Błąd: ${errMsg}` });
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
    // Only mark `dirty: false` for rows that ACTUALLY saved — if 2/5 failed,
    // those 2 must retain their yellow "unsaved" highlight so the admin sees
    // which ones need re-save. (Previously cleared dirty for everyone — data
    // integrity bug found in QA review 2026-05-19.)
    setRows((prev) =>
      prev.map((r) =>
        savedUserIds.has(r.user_id) ? { ...r, dirty: false } : r,
      ),
    );
    setSaveStatus({
      type: failCount === 0 ? "success" : "error",
      message: `Zapisano ${savedUserIds.size}/${dirtyRows.length}${failCount > 0 ? ` (${failCount} błędów)` : ""}`,
    });
  };

  const dirtyCount = rows.filter((r) => r.dirty).length;

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
            <div className="flex items-center gap-2 ml-auto">
              <Calendar className="w-4 h-4 text-muted-foreground" />
              <label className="text-sm text-muted-foreground">Tydzień (pon):</label>
              <input
                type="date"
                value={weekStartDate}
                onChange={(e) => setWeekStartDate(e.target.value)}
                className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              />
              <Button
                variant="outline"
                size="sm"
                onClick={() => entriesQuery.refetch()}
                aria-label="Odśwież listę"
              >
                <RefreshCw className="w-4 h-4" aria-hidden="true" />
              </Button>
              {dirtyCount > 0 && (
                <Button size="sm" onClick={handleSaveAll} disabled={upsertMutation.isPending}>
                  <Save className="w-4 h-4" aria-hidden="true" />
                  <span className="ml-1">Zapisz wszystkie ({dirtyCount})</span>
                </Button>
              )}
            </div>
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

      {/* Data Entry Table */}
      <Card>
        <CardContent className="pt-6">
          {entriesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
          ) : entriesQuery.error ? (
            <p className="text-sm text-destructive py-6 text-center">
              Błąd ładowania wpisów: {String(entriesQuery.error)}
            </p>
          ) : rows.length === 0 ? (
            <div className="py-12 text-center space-y-2">
              <AlertCircle className="w-8 h-8 text-muted-foreground mx-auto" />
              <p className="text-sm text-muted-foreground">
                Brak wpisów dla tygodnia od {weekStartDate}.
              </p>
              <p className="text-xs text-muted-foreground">
                Wpisy zostają utworzone automatycznie jak userzy zapiszą KPI przez{" "}
                <code>/dynareporter/body-leasing</code>. Admin może też wstawić wpis
                bezpośrednio (TODO — formularz nowego wpisu).
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
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      LI CV
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      LI msg
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      LI resp
                    </th>
                    <th className="px-2 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Akcja
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((row) => (
                    <tr
                      key={row.user_id}
                      className={row.dirty ? "bg-amber-50/30 dark:bg-amber-950/10" : ""}
                    >
                      <td className="px-2 py-1.5 text-sm font-medium">{row.user_name}</td>
                      {(
                        [
                          "verifications",
                          "recommendations",
                          "interviews",
                          "placements",
                          "requests",
                          "days_worked",
                          "linkedin_cv_added",
                          "linkedin_messages_sent",
                          "linkedin_responses_received",
                        ] as const
                      ).map((field) => (
                        <td key={field} className="px-1 py-1">
                          <input
                            type="number"
                            min={0}
                            value={row[field]}
                            onChange={(e) =>
                              handleCellChange(row.user_id, field, Number(e.target.value))
                            }
                            className={`w-16 text-center text-sm tabular-nums rounded border px-1 py-0.5 ${highlightZeroClass(row[field])}`}
                          />
                        </td>
                      ))}
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
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
