"use client";

/**
 * BodyLeasingBrowse — zakładka "Przeglądaj dane" dla Rekrutacji.
 *
 * Ruchomy kalendarz (Od / Do, bez podziału na tygodnie) → lista wpisów KPI
 * w wybranym okresie z możliwością usunięcia rekordu. Port "browse" z
 * artur-t-96/InfraReporter (AdminPanel.tsx) na model dat zamiast tygodni.
 */

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Calendar, RefreshCw, Trash2, AlertCircle } from "lucide-react";
import {
  dynareporterBodyLeasingApi,
  type DrKpiBodyLeasingEntry,
  extractErrorMsg,
} from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

function fmtInput(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function BodyLeasingBrowse() {
  const queryClient = useQueryClient();
  const [fromDate, setFromDate] = useState<string>(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return fmtInput(d);
  });
  const [toDate, setToDate] = useState<string>(() => fmtInput(new Date()));
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

  const rows = useMemo(() => {
    const data = entriesQuery.data ?? [];
    return [...data].sort((a, b) => {
      const d = (b.report_date ?? "").localeCompare(a.report_date ?? "");
      if (d !== 0) return d;
      return (a.user_name ?? "").localeCompare(b.user_name ?? "", "pl");
    });
  }, [entriesQuery.data]);

  const handleDelete = (e: DrKpiBodyLeasingEntry) => {
    if (
      !window.confirm(
        `Usunąć wpis ${e.user_name ?? ""} z ${e.report_date}? Tej operacji nie można cofnąć.`,
      )
    )
      return;
    deleteMutation.mutate(e.id);
  };

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
          {status && (
            <p className="mt-3 text-sm text-emerald-600">{status}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {entriesQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              Ładowanie…
            </p>
          ) : rows.length === 0 ? (
            <div className="py-10 text-center space-y-2">
              <AlertCircle className="w-8 h-8 text-muted-foreground mx-auto" />
              <p className="text-sm text-muted-foreground">
                Brak wpisów w okresie {fromDate} – {toDate}.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/40">
                  <tr>
                    {["Data", "Osoba", "Wer.", "Rek.", "Int.", "Plac.", "Req.", "Dni", ""].map(
                      (h, i) => (
                        <th
                          key={h || i}
                          className={`px-2 py-2 text-[10px] font-medium text-muted-foreground uppercase ${
                            i >= 2 && i <= 7 ? "text-center" : "text-left"
                          }`}
                        >
                          {h}
                        </th>
                      ),
                    )}
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
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleDelete(e)}
                          disabled={deleteMutation.isPending}
                          aria-label={`Usuń wpis ${e.user_name ?? ""} z ${e.report_date}`}
                        >
                          <Trash2 className="w-3.5 h-3.5 text-rose-600" />
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
