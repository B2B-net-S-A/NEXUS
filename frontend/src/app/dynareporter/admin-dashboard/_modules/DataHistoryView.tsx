"use client";

/**
 * DataHistoryView — wspólna zakładka "Historia" dla modułów admina DR.
 *
 * Pokazuje historię operacji na danych modułu z `dr_data_audit_log`
 * (filtr po `table_name`) — kto, kiedy, jaka akcja, ile rekordów.
 * Dodatkowo (jeśli są) historia importów Excel z `dr_upload_history`.
 *
 * Port odpowiednika zakładki "Historia" z artur-t-96/InfraReporter
 * (AdminPanel.tsx `activeTab === 'history'`).
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History, FileSpreadsheet, AlertCircle, Calendar } from "lucide-react";
import { dynareporterAdminApi } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

const ACTION_LABEL: Record<string, string> = {
  INSERT: "Dodano",
  UPDATE: "Zmieniono",
  DELETE: "Usunięto",
  UPSERT: "Zapisano",
};

function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pl-PL", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtInput(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Czy data ISO mieści się w okresie [from, to] (porównanie po części dziennej). */
function inRange(iso: string, from: string, to: string): boolean {
  const day = (iso ?? "").slice(0, 10);
  return (!from || day >= from) && (!to || day <= to);
}

interface DataHistoryViewProps {
  /** Logiczna nazwa tabeli w audit logu, np. "kpi_body_leasing". */
  tableName: string;
  /** Prefiks file_type uploadów Excel dla tego modułu, np. "body-leasing". */
  uploadFileType?: string;
  title?: string;
}

export function DataHistoryView({
  tableName,
  uploadFileType,
  title = "Historia zmian",
}: DataHistoryViewProps) {
  const auditQuery = useQuery({
    queryKey: ["dr-audit-log"],
    queryFn: () => dynareporterAdminApi.auditLog(200),
    staleTime: 30_000,
  });
  const uploadsQuery = useQuery({
    queryKey: ["dr-upload-history"],
    queryFn: () => dynareporterAdminApi.uploadHistory(50),
    staleTime: 30_000,
  });

  // Ruchomy kalendarz okresu (Od/Do) — filtruje historię zmian po dacie.
  // Domyślnie od początku bieżącego roku do dziś.
  const [fromDate, setFromDate] = useState<string>(
    () => `${new Date().getFullYear()}-01-01`,
  );
  const [toDate, setToDate] = useState<string>(() => fmtInput(new Date()));

  const auditRows = (auditQuery.data ?? []).filter(
    (r) => r.table_name === tableName && inRange(r.created_at, fromDate, toDate),
  );
  const uploadRows = (uploadsQuery.data ?? []).filter(
    (r) =>
      (!uploadFileType || (r.file_type ?? "").includes(uploadFileType)) &&
      inRange(r.created_at, fromDate, toDate),
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <History className="w-5 h-5 text-violet-600" />
            <h3 className="text-lg font-semibold">{title}</h3>
            {/* Ruchomy kalendarz okresu (bez podziału na tygodnie) */}
            <div className="flex items-center gap-2 ml-auto">
              <Calendar className="w-4 h-4 text-muted-foreground" />
              <label className="text-sm text-muted-foreground">Od:</label>
              <input
                type="date"
                value={fromDate}
                max={toDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                aria-label="Data początkowa okresu historii"
              />
              <label className="text-sm text-muted-foreground">Do:</label>
              <input
                type="date"
                value={toDate}
                min={fromDate}
                onChange={(e) => setToDate(e.target.value)}
                className="px-2 py-1.5 text-sm bg-background border border-input rounded-md"
                aria-label="Data końcowa okresu historii"
              />
            </div>
          </div>

          {auditQuery.isLoading ? (
            <p className="text-sm text-muted-foreground py-6 text-center">
              Ładowanie…
            </p>
          ) : auditRows.length === 0 ? (
            <div className="py-10 text-center space-y-2">
              <AlertCircle className="w-8 h-8 text-muted-foreground mx-auto" />
              <p className="text-sm text-muted-foreground">
                Brak zarejestrowanych zmian danych dla tego modułu.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/40">
                  <tr>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Data
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Akcja
                    </th>
                    <th className="px-3 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Rekordów
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Wykonał
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {auditRows.map((r) => (
                    <tr key={r.id}>
                      <td className="px-3 py-2 tabular-nums whitespace-nowrap">
                        {fmtDateTime(r.created_at)}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                            r.action === "DELETE"
                              ? "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300"
                              : "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                          }`}
                        >
                          {ACTION_LABEL[r.action] ?? r.action}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center tabular-nums">
                        {r.records_count}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {r.performed_by_name ?? "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Historia importów Excel (jeśli były) */}
      {uploadRows.length > 0 && (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 mb-4">
              <FileSpreadsheet className="w-5 h-5 text-emerald-600" />
              <h3 className="text-base font-semibold">Historia importów (Excel)</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-muted/40">
                  <tr>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Data
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Plik
                    </th>
                    <th className="px-3 py-2 text-center text-[10px] font-medium text-muted-foreground uppercase">
                      Rekordów
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Status
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                      Kto
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {uploadRows.map((r) => (
                    <tr key={r.id}>
                      <td className="px-3 py-2 tabular-nums whitespace-nowrap">
                        {fmtDateTime(r.created_at)}
                      </td>
                      <td className="px-3 py-2">{r.file_name || "—"}</td>
                      <td className="px-3 py-2 text-center tabular-nums">
                        {r.records_count}
                      </td>
                      <td className="px-3 py-2">{r.status || "—"}</td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {r.uploaded_by_name}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
