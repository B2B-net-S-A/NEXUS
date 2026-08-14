"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, RotateCcw } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/Toast";
import { financeApi, type FinanceImportRun } from "@/lib/api/finance";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { formatDate } from "@/lib/utils";

function formatBytes(n: number | null): string {
  if (!n) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return formatDate(iso);
  return d.toLocaleString("pl-PL", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function FinanceArchiveTab() {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<number | null>(null);

  const { data, isLoading, isError, refetch } = useQuery<FinanceImportRun[]>({
    queryKey: ["finance-imports"],
    queryFn: async () => (await financeApi.listImports()).data,
  });

  const restore = useMutation({
    mutationFn: (runId: number) => financeApi.restoreImport(runId),
    onSuccess: () => {
      showToast("Wersja przywrócona jako aktualna", "success");
      queryClient.invalidateQueries({ queryKey: ["finance-imports"] });
      queryClient.invalidateQueries({ queryKey: ["finance-periods"] });
      queryClient.invalidateQueries({ queryKey: ["finance-results"] });
    },
    onError: () => showToast("Nie udało się przywrócić wersji", "error"),
  });

  async function handleDownload(run: FinanceImportRun) {
    setBusyId(run.id);
    try {
      await downloadAuthenticatedFile(
        `/api/finance/imports/${run.id}/file`,
        run.source_filename,
      );
    } catch {
      showToast("Nie udało się pobrać pliku.", "error");
    } finally {
      setBusyId(null);
    }
  }

  if (isLoading) {
    return (
      <div className="py-10 text-center text-sm text-muted-foreground">
        Ładowanie archiwum…
      </div>
    );
  }

  // Awaria pobrania NIE może renderować się jak puste archiwum — to czytałoby
  // się jak utrata śladu audytowego.
  if (isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać historii importów."
        onRetry={() => refetch()}
      />
    );
  }

  const runs = data ?? [];
  if (runs.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        Nie wgrano jeszcze żadnego pliku z wynikami.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-muted text-xs uppercase text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left">Okres</th>
            <th className="px-3 py-2 text-left">Data importu</th>
            <th className="px-3 py-2 text-left">Plik</th>
            <th className="px-3 py-2 text-left">Osoba</th>
            <th className="px-3 py-2 text-right">Wiersze</th>
            <th className="px-3 py-2 text-left">Status</th>
            <th className="px-3 py-2 text-right">Akcje</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-t border-border">
              <td className="whitespace-nowrap px-3 py-2 font-medium">{run.label}</td>
              <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                {formatDateTime(run.created_at)}
              </td>
              <td className="px-3 py-2">
                <span className="block max-w-[18rem] truncate">
                  {run.source_filename}
                </span>
                <span className="text-xs text-muted-foreground">
                  {formatBytes(run.size_bytes)}
                </span>
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {run.created_by_email ?? "—"}
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
                {run.row_count}
                {run.rejected_count > 0 && (
                  <span className="ml-1 text-xs text-destructive">
                    (pominięto {run.rejected_count})
                  </span>
                )}
              </td>
              <td className="px-3 py-2">
                <Badge variant={run.status === "current" ? "success" : "neutral"} size="sm">
                  {run.status === "current" ? "Aktualny" : "Zastąpiony"}
                </Badge>
              </td>
              <td className="px-3 py-2 text-right">
                <div className="inline-flex gap-1">
                  <button
                    type="button"
                    title="Pobierz oryginalny plik"
                    disabled={busyId === run.id}
                    onClick={() => handleDownload(run)}
                    className="rounded p-1.5 text-muted-foreground hover:bg-muted disabled:opacity-50"
                  >
                    {busyId === run.id ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Download className="h-4 w-4" />
                    )}
                  </button>
                  {run.status === "superseded" && (
                    <button
                      type="button"
                      title="Przywróć jako aktualny"
                      disabled={restore.isPending}
                      onClick={() => {
                        if (
                          confirm(
                            `Przywrócić wersję z ${formatDateTime(run.created_at)} jako aktualną dla ${run.label}?`,
                          )
                        ) {
                          restore.mutate(run.id);
                        }
                      }}
                      className="rounded p-1.5 text-muted-foreground hover:bg-muted disabled:opacity-50"
                    >
                      <RotateCcw className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
