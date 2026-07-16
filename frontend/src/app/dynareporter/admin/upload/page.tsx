"use client";

/**
 * DynaReporter B.2.11 — historia uploadów (admin, read-only).
 *
 * R0 (plan analytics 2026-07-16): sam upload wycofany (backend: 410 Gone) —
 * strona pokazuje wyłącznie archiwalną historię.
 */

import { useQuery } from "@tanstack/react-query";
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

export default function AdminUploadPage() {
  const { user, hydrated } = useAuthStore();

  const historyQ = useQuery({
    queryKey: ["dr", "upload-history"],
    queryFn: () =>
      api.get<UploadHistoryEntry[]>("/api/dynareporter/upload/history").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "admin"),
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
        <h1 className="text-2xl font-bold tracking-tight">Historia uploadów XLSX</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Archiwum historycznych uploadów DynaReportera (audit log).
        </p>
      </header>

      {/* R0 (plan analytics 2026-07-16): upload wycofany — backend zwraca
          410 Gone. Bieżące statystyki liczy live ATS (Analytics v1). */}
      <section className="rounded-lg border border-amber-300 bg-amber-50 p-5">
        <h2 className="font-semibold mb-1 text-[#7a4c0d]">Upload wycofany</h2>
        <p className="text-sm text-[#7a4c0d]">
          Ręczne wgrywanie XLSX zostało wycofane — bieżące statystyki pochodzą
          wprost z live ATS. Poniższa historia pozostaje jako archiwum.
        </p>
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
