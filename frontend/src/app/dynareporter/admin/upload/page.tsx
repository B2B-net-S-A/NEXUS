"use client";

/**
 * DynaReporter B.2.11 — Upload + History (admin).
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

interface UploadHistoryEntry {
  id: number;
  uploaded_by: number;
  uploader_name?: string;
  file_type: string;
  file_name: string;
  records_count: number;
  status: string;
  error_message?: string;
  created_at: string;
}

const FILE_TYPES = [
  { value: "body_leasing", label: "Body Leasing KPI" },
  { value: "sales", label: "Sales KPI" },
  { value: "finances", label: "Finanse" },
  { value: "mrr_monthly", label: "MRR miesięczny" },
  { value: "sales_weekly", label: "Sales weekly activity" },
];

export default function AdminUploadPage() {
  const { user, hydrated } = useAuthStore();
  const queryClient = useQueryClient();
  const [fileType, setFileType] = useState("body_leasing");
  const [file, setFile] = useState<File | null>(null);

  const historyQ = useQuery({
    queryKey: ["dr", "upload-history"],
    queryFn: () =>
      api.get<UploadHistoryEntry[]>("/api/dynareporter/upload/history").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "admin"),
  });

  const uploadMut = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error("Wybierz plik");
      const formData = new FormData();
      formData.append("file", file);
      const resp = await api.post("/api/dynareporter/upload/excel", formData, {
        params: { file_type: fileType },
        headers: { "Content-Type": "multipart/form-data" },
      });
      return resp.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dr", "upload-history"] });
      setFile(null);
    },
  });

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "admin")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Brak sekcji <code>admin</code> — upload XLSX wymaga uprawnień administracyjnych.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-5xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Upload XLSX + Historia</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Wgrywanie Excel z KPI/MRR/finansów. NOTE: parsing XLSX jest TODO w
          follow-up — obecnie endpoint zapisuje audit log z error_message.
        </p>
      </header>

      <section className="rounded-lg border border-border bg-card p-5">
        <h2 className="font-semibold mb-3">Upload nowego pliku</h2>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Typ pliku
            </label>
            <select
              value={fileType}
              onChange={(e) => setFileType(e.target.value)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            >
              {FILE_TYPES.map((ft) => (
                <option key={ft.value} value={ft.value}>
                  {ft.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Plik XLSX
            </label>
            <input
              type="file"
              accept=".xlsx,.xls"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
          </div>
          <button
            type="button"
            onClick={() => uploadMut.mutate()}
            disabled={!file || uploadMut.isPending}
            className="rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {uploadMut.isPending ? "Wgrywam…" : "Wgraj plik"}
          </button>
          {uploadMut.isSuccess && (
            <p className="text-xs text-muted-foreground">
              Audit log zapisany. Wynik: {uploadMut.data?.status}. {uploadMut.data?.error_message}
            </p>
          )}
          {uploadMut.isError && (
            <p className="text-xs text-destructive">
              Błąd: {(uploadMut.error as Error).message}
            </p>
          )}
        </div>
      </section>

      <section className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Historia uploadów</h2>
        {historyQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (historyQ.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak uploadów.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="pb-2 font-medium">Data</th>
                  <th className="pb-2 font-medium">Użytkownik</th>
                  <th className="pb-2 font-medium">Typ</th>
                  <th className="pb-2 font-medium">Plik</th>
                  <th className="pb-2 font-medium text-right">Rekordy</th>
                  <th className="pb-2 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {(historyQ.data ?? []).map((h) => (
                  <tr key={h.id} className="border-b border-border last:border-0">
                    <td className="py-2 tabular-nums">
                      {new Date(h.created_at).toLocaleString("pl-PL")}
                    </td>
                    <td className="py-2">{h.uploader_name || `User #${h.uploaded_by}`}</td>
                    <td className="py-2 text-muted-foreground">{h.file_type}</td>
                    <td className="py-2 truncate max-w-[200px]">{h.file_name}</td>
                    <td className="py-2 text-right tabular-nums">{h.records_count}</td>
                    <td
                      className={cn(
                        "py-2 font-medium",
                        h.status === "success" && "text-emerald-600",
                        h.status === "failed" && "text-destructive",
                        h.status === "partial" && "text-amber-600"
                      )}
                    >
                      {h.status}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
