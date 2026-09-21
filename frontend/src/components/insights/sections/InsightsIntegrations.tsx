"use client";

/**
 * Integracje — scrapery pracuj.pl / JJIT „widoczne" w NEXUS.
 *
 * Scrapery chodzą poza NEXUS-em (Mac, launchd) i do tej pory jedynym śladem ich
 * pracy były wiadomości na Slacku: brak runu wyglądał jak brak kandydatów.
 * Ta sekcja odpowiada na trzy pytania operatora: czy dziś poszło, co dały
 * (nowi / duplikaty / dopasowania do rekrutacji), co się wysypało — z linkiem
 * do kandydata. Badge „zastój" liczy backend tą samą regułą co alert Slack.
 *
 * Nie jest zależna od `period` — okno jest własne (7/30/90 dni), bo pytanie
 * „czy integracja żyje" nie zna kwartałów.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Copy,
  Loader2,
  RefreshCw,
  Target,
  UserPlus,
  XCircle,
} from "lucide-react";
import Link from "next/link";

import {
  integrationsApi,
  type IntegrationRunDto,
  type IntegrationSourceSummary,
} from "@/lib/integrations-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { KpiCard, LoadingSpinner, SectionError, fmtNumber } from "./_shared";

const WINDOWS = [7, 30, 90] as const;

/** „3 h temu" — wiek liczy się tu bardziej niż data (jak w TraffitSyncCard). */
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

function statusLabel(run: IntegrationRunDto | null): string {
  if (!run) return "brak runów";
  switch (run.status) {
    case "running":
      return "w toku";
    case "ok":
      return "OK";
    case "errors":
      return "OK z błędami";
    case "failed":
      return "nieudany";
  }
}

function stat(run: IntegrationRunDto | null, key: string): number {
  const value = run?.stats?.[key];
  return typeof value === "number" ? value : 0;
}

function SourceCard({ summary }: { summary: IntegrationSourceSummary }) {
  const run = summary.last_run;
  const healthy = !summary.stale && run?.status !== "failed";
  const Icon = healthy ? CheckCircle2 : AlertTriangle;
  return (
    <div className="bg-card dark:bg-muted rounded-2xl border border-border p-5 space-y-4">
      <div className="flex items-start gap-3">
        <div
          className={cn(
            "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl",
            healthy ? "bg-emerald-500/10 text-emerald-600" : "bg-amber-500/10 text-amber-600",
          )}
        >
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-foreground">{summary.label}</h3>
            {summary.stale && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-500">
                zastój &gt; {Math.round(summary.stale_after_hours)} h
              </span>
            )}
            {run?.mode && run.mode !== "import" && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
                {run.mode}
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground flex items-center gap-1.5 mt-1">
            <Clock className="h-3.5 w-3.5" />
            ostatni udany run: {formatAge(summary.last_success_at)}
            {run && (
              <>
                <span aria-hidden="true">·</span>
                ostatni: {statusLabel(run)}
                {run.host ? ` (${run.host})` : ""}
              </>
            )}
          </p>
        </div>
      </div>

      {run ? (
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
          <div>
            <dt className="text-muted-foreground">Nowi w Traffit</dt>
            <dd className="text-lg font-semibold text-foreground">{fmtNumber(stat(run, "created"))}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Duplikaty</dt>
            <dd className="text-lg font-semibold text-foreground">
              {fmtNumber(stat(run, "duplicates"))}
              {stat(run, "cv_refreshed") > 0 && (
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  (📎 {stat(run, "cv_refreshed")} nowych CV)
                </span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Do rekrutacji (NEXUS)</dt>
            <dd className="text-lg font-semibold text-foreground">{fmtNumber(stat(run, "nexus_jobs"))}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">Błędy</dt>
            <dd
              className={cn(
                "text-lg font-semibold",
                stat(run, "errors") > 0 ? "text-rose-500" : "text-foreground",
              )}
            >
              {fmtNumber(stat(run, "errors"))}
            </dd>
          </div>
        </dl>
      ) : (
        <p className="text-sm text-muted-foreground">
          Źródło nie zaraportowało jeszcze żadnego runu.
        </p>
      )}

      {run?.error && (
        <p className="text-xs text-rose-500 break-words" title={run.error}>
          {run.error.length > 200 ? `${run.error.slice(0, 200)}…` : run.error}
        </p>
      )}
    </div>
  );
}

export function InsightsIntegrations() {
  const [days, setDays] = useState<(typeof WINDOWS)[number]>(30);
  const { data, isPending, isSuccess, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["insights", "integrations", days],
    queryFn: () => integrationsApi.summary(days),
    // Runy są dobowe; minuta to i tak częściej, niż cokolwiek się tu zmienia.
    refetchInterval: 60_000,
  });

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: false,
  });

  if (viewState === "loading") {
    return (
      <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
        <LoadingSpinner />
      </section>
    );
  }
  if (isBlockingViewState(viewState) || !data) {
    return (
      <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
        <SectionError label="Integracje" error={error} onRetry={() => refetch()} />
      </section>
    );
  }

  const totals = data.sources.reduce(
    (acc, s) => ({
      created: acc.created + s.totals.created,
      duplicates: acc.duplicates + s.totals.duplicates,
      nexus_jobs: acc.nexus_jobs + s.totals.nexus_jobs,
      errors: acc.errors + s.totals.errors,
    }),
    { created: 0, duplicates: 0, nexus_jobs: 0, errors: 0 },
  );

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Integracje</h2>
          <p className="text-sm text-muted-foreground">
            Scrapery pracuj.pl i JJIT: czy chodzą, co dały, co się wysypało.{" "}
            <Link href="/insights?tab=body-leasing&ch=wyniki#doplyw" className="underline underline-offset-2">
              Lejek per źródło
            </Link>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-border overflow-hidden text-sm">
            {WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                onClick={() => setDays(w)}
                className={cn(
                  "px-3 py-1.5",
                  days === w ? "bg-primary text-primary-foreground" : "bg-card text-muted-foreground",
                )}
              >
                {w} dni
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            className="p-2 rounded-lg border border-border text-muted-foreground hover:text-foreground"
            aria-label="Odśwież"
          >
            {isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {data.sources.map((s) => (
          <SourceCard key={s.source} summary={s} />
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard label={`Nowi kandydaci (${days} dni)`} value={fmtNumber(totals.created)} icon={UserPlus} color="green" />
        <KpiCard label="Duplikaty (znani w Traffit)" value={fmtNumber(totals.duplicates)} icon={Copy} color="blue" />
        <KpiCard label="Dodani do rekrutacji" value={fmtNumber(totals.nexus_jobs)} icon={Target} color="purple" sub="auto-match ≥ próg + must-have" />
        <KpiCard label="Błędy" value={fmtNumber(totals.errors)} icon={XCircle} color={totals.errors > 0 ? "red" : "blue"} />
      </div>

      {data.top_jobs.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-2">Rekrutacje zasilane przez integracje</h3>
          <ul className="grid gap-1 sm:grid-cols-2 text-sm">
            {data.top_jobs.map((j) => (
              <li key={j.job_id} className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-1.5">
                <Link href={`/jobs/${j.job_id}`} className="truncate underline-offset-2 hover:underline">
                  {j.title || `Rekrutacja #${j.job_id}`}
                </Link>
                <span className="text-muted-foreground shrink-0">{j.count}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="text-sm font-semibold text-foreground mb-2">Ostatnie błędy</h3>
        {data.recent_errors.length === 0 ? (
          <p className="text-sm text-muted-foreground">Brak błędów w wybranym oknie.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th className="py-1.5 pr-3 font-medium">Kiedy</th>
                  <th className="py-1.5 pr-3 font-medium">Źródło</th>
                  <th className="py-1.5 pr-3 font-medium">Kandydat</th>
                  <th className="py-1.5 pr-3 font-medium">Oferta</th>
                  <th className="py-1.5 font-medium">Błąd</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_errors.map((e, i) => (
                  <tr key={`${e.run_id}-${e.external_id ?? i}`} className="border-t border-border align-top">
                    <td className="py-1.5 pr-3 whitespace-nowrap">{formatAge(e.occurred_at)}</td>
                    <td className="py-1.5 pr-3">{e.source}</td>
                    <td className="py-1.5 pr-3">
                      {e.candidate_id ? (
                        <Link href={`/candidates/${e.candidate_id}`} className="underline-offset-2 hover:underline">
                          {e.candidate_name || `#${e.candidate_id}`}
                        </Link>
                      ) : (
                        e.candidate_name || e.external_id || "—"
                      )}
                    </td>
                    <td className="py-1.5 pr-3 max-w-[16rem] truncate" title={e.offer_title ?? ""}>{e.offer_title || "—"}</td>
                    <td className="py-1.5 text-rose-500 break-words">{e.error || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
