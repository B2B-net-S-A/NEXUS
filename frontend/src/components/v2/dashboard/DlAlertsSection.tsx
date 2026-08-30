"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { Check, Download, Loader2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  dlAlertsApi,
  dlAlertsExportUrl,
  type DlAlertRead,
  type DlAlertStatus,
} from "@/lib/api/dlAlerts";
import { useAuthStore } from "@/store/auth";
import { hasRole } from "@/store/auth";

function formatMoment(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function AlertRow({
  alert,
  onHandled,
  handling,
}: {
  alert: DlAlertRead;
  onHandled: (id: number) => void;
  handling: boolean;
}) {
  const requiresOrderDecision = alert.alert_type === "md_consultant_ended";
  return (
    <li className="rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {alert.link ? (
            <Link
              href={alert.link}
              className="text-sm font-medium text-foreground hover:text-primary"
            >
              {alert.message}
            </Link>
          ) : (
            <p className="text-sm font-medium text-foreground">{alert.message}</p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">
            {alert.client_name} · {alert.alert_type_label} ·{" "}
            {formatMoment(alert.created_at)}
            {alert.status === "handled"
              ? ` · obsłużone ${formatMoment(alert.handled_at ?? "")} przez ${
                  alert.handled_by_name ?? "—"
                } · reakcja ${alert.reaction_label}`
              : ""}
          </p>
        </div>
        {alert.status === "new" && requiresOrderDecision && alert.link ? (
          <Link
            href={alert.link}
            className="inline-flex shrink-0 items-center rounded-md bg-primary px-2.5 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            Podejmij decyzję
          </Link>
        ) : alert.status === "new" && !requiresOrderDecision ? (
          <button
            type="button"
            onClick={() => onHandled(alert.id)}
            disabled={handling}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            {handling ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <Check className="h-3.5 w-3.5" aria-hidden />
            )}
            Oznacz jako obsłużone
          </button>
        ) : null}
      </div>
    </li>
  );
}

/**
 * Sekcja „Powiadomienia" w dashboardzie Delivery Leada.
 *
 * Osobna od dzwonka w topbarze: tamten zna wyłącznie „przeczytane", a tu każdy
 * wpis ma trwały ślad kto/kiedy sprawę załatwił i ile to trwało — i to ten ślad
 * jest raportem, który da się wyeksportować.
 *
 * Oznaczenie jako obsłużone NIE kasuje wpisu; przenosi go do „Historii”
 * i wstrzymuje dalsze cotygodniowe ponowienia tej samej sprawy.
 */
export function DlAlertsSection() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const user = useAuthStore((s) => s.user);
  const canExportAll = hasRole(user, "admin", "finance");

  const [tab, setTab] = useState<DlAlertStatus>("new");
  const [exporting, setExporting] = useState(false);

  const query = useQuery({
    queryKey: ["dl-alerts", tab],
    queryFn: async () => (await dlAlertsApi.list(tab)).data,
  });

  const markHandled = useMutation({
    mutationFn: (alertId: number) => dlAlertsApi.markHandled(alertId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dl-alerts"] });
      showToast("Oznaczono jako obsłużone", "success");
    },
    onError: () => showToast("Nie udało się oznaczyć powiadomienia.", "error"),
  });

  async function exportXlsx(scope: "mine" | "all") {
    if (exporting) return;
    setExporting(true);
    try {
      // `fetch` + Bearer + blob, nie axios z `responseType:"blob"` — ta druga
      // droga bywa zawodna cross-origin (ta sama decyzja co w eksporcie
      // kontraktów i w `lib/authenticated-files.ts`).
      const token = useAuthStore.getState().token;
      const res = await fetch(dlAlertsExportUrl(scope), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        showToast("Eksport nie powiódł się.", "error");
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `powiadomienia-dl-${new Date()
        .toISOString()
        .slice(0, 10)}.xlsx`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } finally {
      setExporting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Powiadomienia</CardTitle>
        <CardDescription>
          Sprawy do załatwienia na zamówieniach klientów, do których jesteś
          przypisany. Oznaczenie jako obsłużone zostaje w historii.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex gap-2" role="tablist">
            {(
              [
                { key: "new" as const, label: "Nowe", count: query.data?.total_new },
                {
                  key: "handled" as const,
                  label: "Historia",
                  count: query.data?.total_handled,
                },
              ]
            ).map((entry) => (
              <button
                key={entry.key}
                type="button"
                role="tab"
                aria-selected={tab === entry.key}
                onClick={() => setTab(entry.key)}
                className={
                  "rounded-full border px-3 py-1.5 text-xs transition-colors " +
                  (tab === entry.key
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "border-border bg-card text-muted-foreground hover:text-foreground")
                }
              >
                {entry.label}
                {/* Licznik dopiero po udanym pobraniu — „(0)" przed odpowiedzią
                    twierdziłoby, że nic nie ma, zanim cokolwiek wiadomo. */}
                {query.isSuccess ? ` (${entry.count ?? 0})` : ""}
              </button>
            ))}
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => exportXlsx("mine")}
              disabled={exporting}
              className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
            >
              <Download className="h-3.5 w-3.5" aria-hidden /> Eksportuj do Excela
            </button>
            {canExportAll ? (
              <button
                type="button"
                onClick={() => exportXlsx("all")}
                disabled={exporting}
                className="inline-flex items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
              >
                <Download className="h-3.5 w-3.5" aria-hidden /> Eksport zbiorczy
              </button>
            ) : null}
          </div>
        </div>

        {/* Kolejność gałęzi: awaria → nie wiem → pustka → dane. Pusty stan
            wisi na `isSuccess`, bo między ponowieniami react-query ma
            `isLoading === false` przy pustych danych — i ekran twierdziłby
            „brak powiadomień", zanim cokolwiek wiadomo. */}
        {query.isError ? (
          <QueryStateNotice
            state="error"
            description="Nie udało się wczytać powiadomień."
            onRetry={() => query.refetch()}
          />
        ) : !query.isSuccess ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Wczytywanie powiadomień…
          </p>
        ) : query.data.alerts.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            {tab === "new"
              ? "Brak nowych powiadomień."
              : "Brak obsłużonych powiadomień."}
          </p>
        ) : (
          <ul className="space-y-3">
            {query.data.alerts.map((alert) => (
              <AlertRow
                key={alert.id}
                alert={alert}
                handling={
                  markHandled.isPending && markHandled.variables === alert.id
                }
                onHandled={(id) => markHandled.mutate(id)}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
