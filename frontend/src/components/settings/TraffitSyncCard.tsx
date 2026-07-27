"use client";

/**
 * Traffit — stan zaplanowanego importu Traffit → NEXUS.
 *
 * Dopóki Traffit jest źródłem prawdy, świeżość tego importu decyduje o tym, czy
 * dane w NEXUS w ogóle są aktualne. Backend wystawiał to od zawsze
 * (`GET /api/admin/traffit/sync/status`), ale Ustawienia pokazywały M365,
 * Fireflies, CloudTalk i Teams — Traffita nie było. Efekt: `traffit=degraded`
 * w `/api/health` był sygnałem, którego nie dało się kliknąć, a przyczynę
 * trzeba było wyciągać zapytaniem do produkcyjnej bazy.
 *
 * Karta odpowiada na trzy pytania operatora: kiedy ostatnio poszło, co jest
 * zepsute, i które wiersze czekają na człowieka.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, Loader2, RefreshCw } from "lucide-react";

import { traffitSyncApi } from "@/lib/api";
import { cn } from "@/lib/utils";

const DAILY_MARKER = "__daily__";
const FULL_MARKER = "__full__";

/** „przed 3 godzinami" — wiek liczy się tu bardziej niż sama data. */
function formatAge(iso: string | null): string {
  if (!iso) return "nigdy";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "nieznany";
  const minutes = Math.floor((Date.now() - then) / 60_000);
  if (minutes < 1) return "przed chwilą";
  if (minutes < 60) return `${minutes} min temu`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h temu`;
  return `${Math.floor(hours / 24)} dni temu`;
}

function errorCount(stats: Record<string, unknown> | null): number {
  const value = stats?.["errors"];
  return typeof value === "number" ? value : 0;
}

export function TraffitSyncCard() {
  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["traffit-sync-status"],
    queryFn: () => traffitSyncApi.status(),
    // Kandydaci i etapy zmieniają się w rytmie dziennym — odpytywanie częściej
    // niż raz na minutę nic nie wnosi, a to endpoint admina.
    refetchInterval: 60_000,
  });

  if (isLoading) {
    return (
      <div className="bg-card dark:bg-muted rounded-2xl border border-border p-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Wczytywanie stanu Traffita…
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="bg-card dark:bg-muted rounded-2xl border border-border p-6">
        <h3 className="text-base font-bold text-foreground">Traffit</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Nie udało się pobrać stanu synchronizacji. Endpoint jest dostępny tylko
          dla administratora.
        </p>
      </div>
    );
  }

  const daily = data.states.find((s) => s.phase === DAILY_MARKER);
  const full = data.states.find((s) => s.phase === FULL_MARKER);
  const phases = data.states.filter(
    (s) => s.phase !== DAILY_MARKER && s.phase !== FULL_MARKER,
  );
  const failing = phases.filter((p) => p.last_status !== "ok");
  const healthy = data.enabled && daily?.last_status === "ok";

  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border p-6">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-xl",
              healthy ? "bg-emerald-500/10" : "bg-amber-500/10",
            )}
          >
            {healthy ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            ) : (
              <AlertTriangle className="h-5 w-5 text-amber-600" />
            )}
          </div>
          <div>
            <h3 className="text-base font-bold text-foreground">Traffit</h3>
            <p className="text-xs text-muted-foreground">
              {data.enabled
                ? "Import Traffit → NEXUS, codziennie o 02:00 UTC"
                : "Wyłączony (TRAFFIT_SYNC_ENABLED=false)"}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", isFetching && "animate-spin")} />
          Odśwież
        </button>
      </div>

      {data.running && (
        <p className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary/10 px-3 py-2 text-xs text-primary">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          Synchronizacja trwa…
        </p>
      )}

      <dl className="mt-5 grid gap-4 sm:grid-cols-3">
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            Ostatni przebieg
          </dt>
          <dd className="mt-1 text-sm font-medium text-foreground">
            {formatAge(daily?.last_run_finished_at ?? null)}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            Znacznik delty
          </dt>
          <dd
            className={cn(
              "mt-1 text-sm font-medium",
              // Zamrożony watermark to najcichszy tryb awarii tego importu:
              // sync „działa", a okno delty rośnie każdej nocy.
              daily?.last_synced_at &&
                Date.now() - new Date(daily.last_synced_at).getTime() >
                  72 * 3_600_000
                ? "text-amber-600"
                : "text-foreground",
            )}
          >
            {formatAge(daily?.last_synced_at ?? null)}
          </dd>
        </div>
        <div>
          <dt className="text-xs uppercase tracking-wide text-muted-foreground">
            Pełny reconcile
          </dt>
          <dd className="mt-1 text-sm font-medium text-foreground">
            {formatAge(full?.last_run_finished_at ?? null)}
          </dd>
        </div>
      </dl>

      {failing.length > 0 && (
        <div className="mt-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Fazy z błędami ({failing.length} z {phases.length})
          </p>
          <ul className="mt-2 space-y-1.5">
            {failing.map((p) => (
              <li
                key={p.phase}
                className="flex items-center justify-between rounded-lg border border-border bg-background/40 px-3 py-2 text-sm"
              >
                <span className="font-medium text-foreground">{p.phase}</span>
                <span className="text-xs text-muted-foreground">
                  {errorCount(p.stats)} błędów · {formatAge(p.last_run_finished_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.quarantined.length > 0 && (
        <div className="mt-5 rounded-xl border border-amber-500/40 bg-amber-500/5 p-4">
          <p className="flex items-center gap-2 text-sm font-medium text-amber-700 dark:text-amber-400">
            <AlertTriangle className="h-4 w-4" />
            Wiersze odłożone do kwarantanny ({data.quarantined.length})
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Nie zaimportowały się {data.max_row_attempts} razy z rzędu, więc
            przestały blokować znacznik delty dla pozostałych rekordów. Wymagają
            ręcznego rozstrzygnięcia — nie znikną same.
          </p>
          <ul className="mt-3 space-y-1">
            {data.quarantined.slice(0, 10).map((row) => (
              <li
                key={`${row.phase}:${row.ref}`}
                className="flex items-center justify-between gap-3 text-xs"
              >
                <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-foreground">
                  {row.ref}
                </code>
                <span className="text-muted-foreground">
                  {row.phase} · {row.attempts ?? "?"} prób
                </span>
              </li>
            ))}
          </ul>
          {data.quarantined.length > 10 && (
            <p className="mt-2 text-xs text-muted-foreground">
              …i {data.quarantined.length - 10} więcej.
            </p>
          )}
        </div>
      )}

      {data.enabled && failing.length === 0 && data.quarantined.length === 0 && (
        <p className="mt-5 inline-flex items-center gap-2 text-xs text-muted-foreground">
          <Clock className="h-3.5 w-3.5" />
          Wszystkie {phases.length} faz zaimportowało się bez błędów.
        </p>
      )}
    </div>
  );
}
