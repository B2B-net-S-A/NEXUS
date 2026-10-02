"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, RotateCcw } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { financeApi, type FinanceImportRun } from "@/lib/api/finance";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import {
  CALM_AMOUNT,
  CALM_EMPTY,
  CALM_HEAD,
  CALM_ROW,
  CALM_SUBLINE,
} from "@/lib/calm-table";
import { cn, formatDate } from "@/lib/utils";

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

export function FinanceArchiveTab({ canWrite = true }: { canWrite?: boolean }) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<number | null>(null);
  // Potwierdzenie w oknie aplikacji — natywny `confirm` zamraża automatyzację
  // przeglądarki (testy E2E, przeklikanie), a jego treści nie da się ostylować.
  const [pendingRestore, setPendingRestore] = useState<FinanceImportRun | null>(
    null,
  );

  const { data, isLoading, isError, refetch } = useQuery<FinanceImportRun[]>({
    queryKey: ["finance-imports"],
    queryFn: async () => (await financeApi.listImports()).data,
  });

  const restore = useMutation({
    mutationFn: (runId: number) => financeApi.restoreImport(runId),
    onSuccess: () => {
      setPendingRestore(null);
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
    <div className="relative overflow-x-auto rounded-[10px] border border-border bg-card">
      <table className="w-full min-w-[56rem] text-[13px]">
        <thead className={cn("bg-background", CALM_HEAD)}>
          <tr className="border-b border-border">
            <th className="px-3.5 py-2 text-left font-semibold">Okres</th>
            <th className="px-3.5 py-2 text-left font-semibold">Data importu</th>
            <th className="px-3.5 py-2 text-left font-semibold">Plik</th>
            <th className="px-3.5 py-2 text-left font-semibold">Osoba</th>
            <th className="px-3.5 py-2 text-right font-semibold">Wiersze</th>
            <th className="px-3.5 py-2 text-left font-semibold">Status</th>
            <th className="px-3.5 py-2 text-right font-semibold">Akcje</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className={cn(CALM_ROW, "h-[50px] last:border-b-0")}>
              <td className="whitespace-nowrap px-3.5 py-1.5 font-semibold">{run.label}</td>
              <td className="whitespace-nowrap px-3.5 py-1.5 tabular-nums">
                {formatDateTime(run.created_at)}
              </td>
              <td className="px-3.5 py-1.5">
                <span className="block max-w-[18rem] truncate font-semibold">
                  {run.source_filename}
                </span>
                <span className={CALM_SUBLINE}>{formatBytes(run.size_bytes)}</span>
              </td>
              <td className="px-3.5 py-1.5">
                {run.created_by_email ?? <span className={CALM_EMPTY}>—</span>}
              </td>
              <td className={cn("px-3.5 py-1.5", CALM_AMOUNT)}>
                {run.row_count}
                {run.rejected_count > 0 && (
                  <span className="mt-0.5 block">
                    <Badge variant="warning" size="sm">
                      pominięto {run.rejected_count}
                    </Badge>
                  </span>
                )}
              </td>
              <td className="px-3.5 py-1.5">
                <StatusDot tone={run.status === "current" ? "success" : "neutral"}>
                  {run.status === "current" ? "Aktualny" : "Zastąpiony"}
                </StatusDot>
              </td>
              <td className="px-3.5 py-1.5 text-right">
                <div className="inline-flex items-center gap-1.5">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    title="Pobierz oryginalny plik"
                    disabled={busyId === run.id}
                    onClick={() => handleDownload(run)}
                  >
                    {busyId === run.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    ) : (
                      <Download className="h-3.5 w-3.5" aria-hidden />
                    )}
                    Pobierz oryginał
                  </Button>
                  {canWrite && run.status === "superseded" && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      title="Przywróć jako aktualny"
                      disabled={restore.isPending}
                      onClick={() => setPendingRestore(run)}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <RotateCcw className="h-3.5 w-3.5" aria-hidden />
                      Przywróć jako aktualny
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {pendingRestore && (
        <AppModal
          open
          onOpenChange={(next) => {
            if (!next && !restore.isPending) setPendingRestore(null);
          }}
          title="Przywrócić tę wersję?"
          footer={
            <>
              <button
                type="button"
                onClick={() => setPendingRestore(null)}
                disabled={restore.isPending}
                className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
              >
                Anuluj
              </button>
              <button
                type="button"
                onClick={() => restore.mutate(pendingRestore.id)}
                disabled={restore.isPending}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {restore.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
                Przywróć
              </button>
            </>
          }
        >
          <div className="space-y-2 text-sm">
            <p>
              Wersja z <strong>{formatDateTime(pendingRestore.created_at)}</strong>{" "}
              stanie się aktualna dla <strong>{pendingRestore.label}</strong>.
            </p>
            <p className="text-muted-foreground">
              Obecna wersja nie zostanie usunięta — trafi do Archiwum ze statusem
              „Zastąpiony” i można ją przywrócić.
            </p>
          </div>
        </AppModal>
      )}
    </div>
  );
}
