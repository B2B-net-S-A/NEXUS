"use client";

/**
 * BodyLeasingBrowse – zakładka "Przeglądaj dane" dla Rekrutacji.
 *
 * Ruchomy kalendarz (Od / Do, bez podziału na tygodnie) → lista wpisów KPI
 * w wybranym okresie. Funkcje (parytet z artur-t-96/InfraReporter AdminPanel):
 * - wyszukiwarka pracownika (lupka + filtr po nazwisku)
 * - sortowanie po kliknięciu w nagłówek (Data/Osoba/Wer/Rek/Int/Plac/Req/Dni)
 * - wiersz sum kolumn na dole
 * - usuwanie rekordu
 */

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, RefreshCw, Trash2, AlertCircle, Search, Pencil } from "lucide-react";
import {
  dynareporterBodyLeasingApi,
  type DrKpiBodyLeasingEntry,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";

/** Pola KPI edytowalne w modalu (numeryczne). */
const EDIT_FIELDS: { key: keyof DrKpiBodyLeasingEntry; label: string }[] = [
  { key: "verifications", label: "Weryfikacje" },
  { key: "recommendations", label: "Rekomendacje" },
  { key: "interviews", label: "Interviews" },
  { key: "placements", label: "Placements" },
  { key: "requests", label: "Zamknięte zapytania" },
  { key: "days_worked", label: "Dni robocze" },
  { key: "linkedin_cv_added", label: "LinkedIn – CV dodane" },
  { key: "linkedin_messages_sent", label: "LinkedIn – wiadomości" },
  { key: "linkedin_responses_received", label: "LinkedIn – odpowiedzi" },
];

function fmtInput(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

type SortKey =
  | "report_date"
  | "user_name"
  | "verifications"
  | "recommendations"
  | "interviews"
  | "placements"
  | "requests"
  | "days_worked";

const NUMERIC_COLS = new Set<SortKey>([
  "verifications",
  "recommendations",
  "interviews",
  "placements",
  "requests",
  "days_worked",
]);

export function BodyLeasingBrowse() {
  const queryClient = useQueryClient();
  const [fromDate, setFromDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return fmtInput(d);
  });
  const [toDate, setToDate] = useState<string>(() => fmtInput(new Date()));
  const [search, setSearch] = useState("");
  const [sortConfig, setSortConfig] = useState<{ key: SortKey; dir: "asc" | "desc" }>({
    key: "report_date",
    dir: "desc",
  });
  const [status, setStatus] = useState<string | null>(null);

  const entriesQuery = useQuery({
    queryKey: ["dr-bl-browse", fromDate, toDate],
    queryFn: () =>
      dynareporterBodyLeasingApi.allEntries({
        from_date: fromDate,
        to_date: toDate,
      }),
    staleTime: 30_000,
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => dynareporterBodyLeasingApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-bl-browse"] });
      queryClient.invalidateQueries({ queryKey: ["dr-bl-admin-entries"] });
      queryClient.invalidateQueries({ queryKey: ["dr-rekrutacja-dashboard"] });
      setStatus("Usunięto wpis.");
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => setStatus(`Błąd: ${extractErrorMsg(e)}`),
  });

  // Edycja wiersza (ikona ołówka) – upsert po (user_id, report_date).
  const [editRow, setEditRow] = useState<DrKpiBodyLeasingEntry | null>(null);
  const [editVals, setEditVals] = useState<Record<string, number>>({});

  const editMutation = useMutation({
    mutationFn: () => {
      if (!editRow) throw new Error("Brak wiersza do edycji");
      return dynareporterBodyLeasingApi.upsert({
        user_id: editRow.user_id,
        report_date: editRow.report_date,
        week_number: editRow.week_number,
        is_draft: editRow.is_draft,
        ...editVals,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr-bl-browse"] });
      queryClient.invalidateQueries({ queryKey: ["dr-bl-admin-entries"] });
      queryClient.invalidateQueries({ queryKey: ["dr-rekrutacja-dashboard"] });
      setEditRow(null);
      setStatus("Zapisano zmiany.");
      setTimeout(() => setStatus(null), 3000);
    },
    onError: (e: unknown) => setStatus(`Błąd: ${extractErrorMsg(e)}`),
  });

  const openEdit = (row: DrKpiBodyLeasingEntry) => {
    setEditVals(
      Object.fromEntries(
        EDIT_FIELDS.map((f) => [f.key, (row[f.key] as number) ?? 0]),
      ),
    );
    setEditRow(row);
  };

  const handleSort = (key: SortKey) => {
    setSortConfig((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
        : { key, dir: NUMERIC_COLS.has(key) ? "desc" : "asc" },
    );
  };

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    const data = (entriesQuery.data ?? []).filter((e) =>
      term ? (e.user_name ?? "").toLowerCase().includes(term) : true,
    );
    const { key, dir } = sortConfig;
    const mul = dir === "asc" ? 1 : -1;
    return [...data].sort((a, b) => {
      if (key === "user_name") {
        return (a.user_name ?? "").localeCompare(b.user_name ?? "", "pl") * mul;
      }
      if (key === "report_date") {
        return (a.report_date ?? "").localeCompare(b.report_date ?? "") * mul;
      }
      const av = (a[key] as number) ?? 0;
      const bv = (b[key] as number) ?? 0;
      return (av - bv) * mul;
    });
  }, [entriesQuery.data, search, sortConfig]);

  const totals = useMemo(
    () =>
      rows.reduce(
        (acc, e) => ({
          verifications: acc.verifications + (e.verifications ?? 0),
          recommendations: acc.recommendations + (e.recommendations ?? 0),
          interviews: acc.interviews + (e.interviews ?? 0),
          placements: acc.placements + (e.placements ?? 0),
          requests: acc.requests + (e.requests ?? 0),
          days_worked: acc.days_worked + (e.days_worked ?? 0),
        }),
        {
          verifications: 0,
          recommendations: 0,
          interviews: 0,
          placements: 0,
          requests: 0,
          days_worked: 0,
        },
      ),
    [rows],
  );

  const handleDelete = (e: DrKpiBodyLeasingEntry) => {
    if (
      !window.confirm(
        `Usunąć wpis ${e.user_name ?? ""} z ${e.report_date}? Tej operacji nie można cofnąć.`,
      )
    )
      return;
    deleteMutation.mutate(e.id);
  };

  const COLUMNS: { key: SortKey; label: string; align: "left" | "center" }[] = [
    { key: "report_date", label: "Data", align: "left" },
    { key: "user_name", label: "Osoba", align: "left" },
    { key: "verifications", label: "Wer.", align: "center" },
    { key: "recommendations", label: "Rek.", align: "center" },
    { key: "interviews", label: "Int.", align: "center" },
    { key: "placements", label: "Plac.", align: "center" },
    { key: "requests", label: "Req.", align: "center" },
    { key: "days_worked", label: "Dni", align: "center" },
  ];

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-center gap-3">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            <label className="text-sm text-muted-foreground">Od:</label>
            <input
              type="date"
              value={fromDate}
              max={toDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              aria-label="Data początkowa okresu"
            />
            <label className="text-sm text-muted-foreground">Do:</label>
            <input
              type="date"
              value={toDate}
              min={fromDate}
              onChange={(e) => setToDate(e.target.value)}
              className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
              aria-label="Data końcowa okresu"
            />

            {/* Wyszukiwarka pracownika */}
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Szukaj pracownika…"
                className="pl-8 pr-2 py-1.5 text-sm bg-background border border-input rounded-md w-52"
                aria-label="Szukaj pracownika po imieniu lub nazwisku"
              />
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={() => entriesQuery.refetch()}
              aria-label="Odśwież"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
            </Button>
            <span className="text-xs text-muted-foreground ml-auto">
              {rows.length} {rows.length === 1 ? "wpis" : "wpisów"}
            </span>
          </div>
          {status && <p className="mt-3 text-sm text-emerald-600">{status}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {entriesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">Ładowanie…</p>
          ) : rows.length === 0 ? (
            <div className="py-10 text-center space-y-2">
              <AlertCircle className="w-8 h-8 text-muted-foreground mx-auto" />
              <p className="text-sm text-muted-foreground">
                {search
                  ? `Brak wpisów dla "${search}" w okresie ${fromDate} – ${toDate}.`
                  : `Brak wpisów w okresie ${fromDate} – ${toDate}.`}
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/40">
                  <tr>
                    {COLUMNS.map((col) => {
                      const active = sortConfig.key === col.key;
                      return (
                        <th
                          key={col.key}
                          onClick={() => handleSort(col.key)}
                          className={`px-2 py-2 text-[10px] font-medium uppercase cursor-pointer select-none hover:text-foreground ${
                            col.align === "center" ? "text-center" : "text-left"
                          } ${active ? "text-primary" : "text-muted-foreground"}`}
                          aria-sort={
                            active
                              ? sortConfig.dir === "asc"
                                ? "ascending"
                                : "descending"
                              : "none"
                          }
                        >
                          {col.label}
                          {active ? (sortConfig.dir === "asc" ? " ▲" : " ▼") : ""}
                        </th>
                      );
                    })}
                    <th className="px-2 py-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {rows.map((e) => (
                    <tr key={e.id}>
                      <td className="px-2 py-1.5 tabular-nums whitespace-nowrap">
                        {e.report_date}
                      </td>
                      <td className="px-2 py-1.5 font-medium">{e.user_name}</td>
                      <td className="px-2 py-1.5 text-center tabular-nums">
                        {e.verifications ?? 0}
                      </td>
                      <td className="px-2 py-1.5 text-center tabular-nums">
                        {e.recommendations ?? 0}
                      </td>
                      <td className="px-2 py-1.5 text-center tabular-nums">
                        {e.interviews ?? 0}
                      </td>
                      <td className="px-2 py-1.5 text-center tabular-nums">
                        {e.placements ?? 0}
                      </td>
                      <td className="px-2 py-1.5 text-center tabular-nums">
                        {e.requests ?? 0}
                      </td>
                      <td className="px-2 py-1.5 text-center tabular-nums">
                        {e.days_worked ?? 0}
                      </td>
                      <td className="px-2 py-1.5 text-center">
                        <div className="flex items-center justify-center gap-0.5">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => openEdit(e)}
                            aria-label={`Edytuj wpis ${e.user_name ?? ""} z ${e.report_date}`}
                          >
                            <Pencil className="w-3.5 h-3.5 text-violet-600" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => handleDelete(e)}
                            disabled={deleteMutation.isPending}
                            aria-label={`Usuń wpis ${e.user_name ?? ""} z ${e.report_date}`}
                          >
                            <Trash2 className="w-3.5 h-3.5 text-rose-600" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="border-t-2 border-border bg-muted/30 font-semibold">
                  <tr>
                    <td className="px-2 py-2" />
                    <td className="px-2 py-2 text-right text-xs uppercase text-muted-foreground">
                      Suma:
                    </td>
                    <td className="px-2 py-2 text-center tabular-nums">
                      {totals.verifications}
                    </td>
                    <td className="px-2 py-2 text-center tabular-nums">
                      {totals.recommendations}
                    </td>
                    <td className="px-2 py-2 text-center tabular-nums">
                      {totals.interviews}
                    </td>
                    <td className="px-2 py-2 text-center tabular-nums">
                      {totals.placements}
                    </td>
                    <td className="px-2 py-2 text-center tabular-nums">
                      {totals.requests}
                    </td>
                    <td className="px-2 py-2 text-center tabular-nums">
                      {totals.days_worked}
                    </td>
                    <td className="px-2 py-2" />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Modal edycji wiersza (ikona ołówka) */}
      <Dialog open={editRow !== null} onOpenChange={(o) => !o && setEditRow(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>
              Edytuj wpis – {editRow?.user_name} ({editRow?.report_date})
            </DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-3 py-2">
            {EDIT_FIELDS.map((f) => (
              <div key={String(f.key)} className="space-y-1">
                <label className="text-xs text-muted-foreground">{f.label}</label>
                <Input
                  type="number"
                  min={0}
                  value={editVals[f.key] ?? 0}
                  onChange={(ev) =>
                    setEditVals((prev) => ({
                      ...prev,
                      [f.key]: Math.max(0, Number(ev.target.value) || 0),
                    }))
                  }
                />
              </div>
            ))}
          </div>
          {editRow && status && status.startsWith("Błąd") && (
            <p className="text-sm text-rose-600">{status}</p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditRow(null)}>
              Anuluj
            </Button>
            <Button
              onClick={() => editMutation.mutate()}
              disabled={editMutation.isPending}
            >
              {editMutation.isPending ? "Zapisywanie…" : "Zapisz"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
