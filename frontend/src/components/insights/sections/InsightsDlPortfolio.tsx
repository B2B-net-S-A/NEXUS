"use client";

import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Award, Briefcase, Loader2, Trophy, Users } from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsDlPortfolioClient,
  type InsightsDlPortfolioLead,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { DL_HIT_RATIO_PORTFOLIO_NOTE } from "@/lib/insights-views";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { barWidth, count, pct } from "./InsightsFormat";
import { KpiCard, SectionError } from "./_shared";

/** Kolor paska hit ratio — ten sam próg co leaderboard klientów. */
export function hitRatioTone(value: number | null): string {
  if (value === null) return "bg-muted-foreground/40";
  if (value >= 50) return "bg-success";
  if (value >= 20) return "bg-warning";
  return "bg-destructive";
}

/** Klient wymaga uwagi — spadek hit ratio albo brak placementów przy zapytaniach. */
export function clientNeedsAttention(c: InsightsDlPortfolioClient): boolean {
  return c.alert !== null;
}

/** Filtr „Tylko z uwagami" na poziomie DL: zostają DL-e z choć jednym takim klientem. */
export function filterLeadsWithAlerts(
  leads: InsightsDlPortfolioLead[],
): InsightsDlPortfolioLead[] {
  return leads
    .map((lead) => ({
      ...lead,
      clients: lead.clients.filter(clientNeedsAttention),
    }))
    .filter((lead) => lead.clients.length > 0);
}

function Sparkline({ values }: { values: number[] }) {
  const max = Math.max(1, ...values);
  return (
    <div className="flex h-8 items-end gap-0.5" aria-hidden="true">
      {values.map((v, i) => (
        <span
          key={i}
          className="w-2.5 rounded-sm bg-primary/60"
          style={{ height: `${Math.round((v / max) * 28) + 3}px` }}
        />
      ))}
    </div>
  );
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Portfele Delivery Leadów (rozdział Klienci, wariant 2 z makiet 21.09.2026).
 *
 * Jedna tabela zamiast dawnych czterech sekcji (ranking DL, placementy per
 * klient, hit ratio klientów, hiring managerowie): DL jest nagłówkiem grupy,
 * a pod nim jego klienci. Nagłówek i wiersze liczy ten sam endpoint tą samą
 * definicją, więc suma wierszy zgadza się z nagłówkiem.
 */
export function InsightsDlPortfolio({
  period,
}: {
  period: InsightsPeriodParams;
}) {
  const [onlyAlerts, setOnlyAlerts] = useState(false);
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.dlPortfolio(period),
    queryFn: () => insightsBoardApi.dlPortfolio(period),
  });

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: (data?.leads.length ?? 0) === 0,
  });

  const leads = data
    ? onlyAlerts
      ? filterLeadsWithAlerts(data.leads)
      : data.leads
    : [];
  const alertCount = data
    ? data.leads.reduce(
        (n, l) => n + l.clients.filter(clientNeedsAttention).length,
        0,
      )
    : 0;
  const target = data?.hit_ratio_target_pct ?? 30;
  // Kolumna HM tylko gdy ktokolwiek ją ma — na produkcji (09.2026) żadna
  // rekrutacja body leasing nie ma przypisanego hiring managera, a kolumna
  // samych myślników udawałaby, że dane są, tylko puste.
  const showHm = leads.some((l) =>
    l.clients.some((c) => c.top_hiring_manager !== null),
  );
  const columns = showHm ? 8 : 7;

  return (
    <section className="bg-card rounded-xl border border-border p-4 shadow-xs space-y-4 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
            <Briefcase className="w-5 h-5 text-primary" />
            Portfele Delivery Leadów
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Każdy DL z jego klientami · tylko rekrutacje body leasing · 🏆 = hit
            ratio ≥ {target}%
          </p>
        </div>
        <div
          role="group"
          aria-label="Filtr portfeli"
          className="inline-flex gap-0.5 rounded-lg bg-muted p-1"
        >
          {[
            { on: false, label: "Wszyscy" },
            { on: true, label: `Tylko z uwagami (${alertCount})` },
          ].map((opt) => (
            <button
              key={opt.label}
              type="button"
              aria-pressed={onlyAlerts === opt.on}
              onClick={() => setOnlyAlerts(opt.on)}
              className={cn(
                "min-h-8 rounded-md px-3 text-xs font-semibold transition-colors",
                onlyAlerts === opt.on
                  ? "bg-card text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {viewState === "loading" ? (
        <div className="py-10 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Portfele Delivery Leadów"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak rekrutacji body leasing w tym okresie.
        </p>
      ) : data ? (
        <>
          {onlyAlerts && leads.length === 0 ? (
            <p className="rounded-lg bg-muted/50 py-6 text-center text-sm text-muted-foreground">
              Żaden klient nie wymaga teraz uwagi.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/40">
                  <tr className="text-left text-xs font-semibold text-muted-foreground">
                    {/* Kolumna „Klient" przyklejona przy przewijaniu w poziomie. */}
                    <th scope="col" className="sticky left-0 z-10 bg-card bg-linear-to-r from-muted/40 to-muted/40 px-4 py-2.5">Klient</th>
                    <th scope="col" className="px-3 py-2.5 text-right">Otwarte</th>
                    <th scope="col" className="px-3 py-2.5 text-right">Zapytania</th>
                    <th scope="col" className="px-3 py-2.5 text-right">Placementy</th>
                    <th scope="col" className="px-3 py-2.5">Hit ratio</th>
                    <th scope="col" className="px-3 py-2.5">6 mies.</th>
                    {showHm ? (
                      <th scope="col" className="px-3 py-2.5">Hiring manager</th>
                    ) : null}
                    <th scope="col" className="px-3 py-2.5">Uwaga</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((lead) => (
                    <Fragment key={lead.dl_id}>
                      <tr className="border-t border-border bg-muted/60">
                        <td colSpan={columns} className="px-4 py-3">
                          <div className="flex flex-wrap items-center gap-3">
                            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                              {initials(lead.dl_name)}
                            </span>
                            <span className="font-semibold text-foreground">
                              {lead.dl_name}
                            </span>
                            {!lead.is_active ? (
                              <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                                konto nieaktywne
                              </span>
                            ) : null}
                            {/* `ml-auto` dopiero od `md`: w przewijanej tabeli liczby DL
                                lądowały przy prawej krawędzi, poza kadrem telefonu. */}
                            <span className="flex flex-wrap items-center gap-2 text-xs md:ml-auto">
                              <span className="rounded-full bg-primary/10 px-2.5 py-1 font-semibold text-primary">
                                {count(lead.placements)} plac. · {count(lead.requests)} zap.
                              </span>
                              <span
                                className={cn(
                                  "rounded-full px-2.5 py-1 font-semibold",
                                  lead.target_achieved
                                    ? "bg-success-muted text-success-muted-foreground"
                                    : "bg-warning-muted text-warning-muted-foreground",
                                )}
                              >
                                hit ratio {pct(lead.hit_ratio)}
                              </span>
                              {lead.target_achieved ? (
                                <Trophy
                                  className="h-4 w-4 text-warning"
                                  aria-label={`Cel ${target}% osiągnięty`}
                                />
                              ) : null}
                            </span>
                          </div>
                        </td>
                      </tr>
                      {lead.clients.map((c) => (
                        <tr
                          key={`${lead.dl_id}-${c.client_id ?? "none"}`}
                          className="border-t border-border"
                        >
                          <td className="sticky left-0 z-10 bg-card px-4 py-3 pl-6 font-semibold sm:pl-14 text-foreground">
                            {c.client_name}
                          </td>
                          <td className="px-3 py-3 text-right tabular-nums">{count(c.open_jobs)}</td>
                          <td className="px-3 py-3 text-right tabular-nums">{count(c.requests)}</td>
                          <td className="px-3 py-3 text-right font-bold tabular-nums">{count(c.placements)}</td>
                          <td className="px-3 py-3">
                            <div className="flex min-w-32 items-center gap-2">
                              <div className="h-1.5 flex-1 rounded-full bg-muted">
                                <div
                                  className={cn("h-1.5 rounded-full", hitRatioTone(c.hit_ratio))}
                                  style={{ width: `${barWidth(c.hit_ratio)}%` }}
                                />
                              </div>
                              <span className="w-12 text-right font-semibold tabular-nums">
                                {pct(c.hit_ratio, 0)}
                              </span>
                            </div>
                          </td>
                          <td className="px-3 py-3">
                            <Sparkline values={c.monthly_placements.map((m) => m.placements)} />
                          </td>
                          {showHm ? (
                          <td className="px-3 py-3 text-xs">
                            {c.top_hiring_manager ? (
                              <>
                                <div className="font-semibold text-foreground">
                                  {c.top_hiring_manager.name}
                                </div>
                                <div className="text-muted-foreground">
                                  {c.top_hiring_manager.title ?? "—"} ·{" "}
                                  {count(c.top_hiring_manager.jobs)} rekr.
                                </div>
                              </>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </td>
                          ) : null}
                          <td className="px-3 py-3">
                            {c.alert === "hit_ratio_drop" ? (
                              <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-destructive/10 px-2.5 py-1 text-xs font-semibold text-destructive">
                                <AlertTriangle className="h-3 w-3" />
                                hit ratio {c.delta_pp !== null ? `${c.delta_pp.toFixed(0)} pp` : "spadek"}
                              </span>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {DL_HIT_RATIO_PORTFOLIO_NOTE}
          </p>
          {data.unattributed.requests > 0 || data.unattributed.placements > 0 ? (
            <p className="text-xs text-muted-foreground">
              Bez przypisanego DL: {count(data.unattributed.requests)} zapytań ·{" "}
              {count(data.unattributed.placements)} placementów
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

/** Cztery liczby nad portfelami — z tej samej odpowiedzi co nagłówki DL. */
export function DlPortfolioTiles({ period }: { period: InsightsPeriodParams }) {
  const { data } = useQuery({
    queryKey: insightsQueryKeys.dlPortfolio(period),
    queryFn: () => insightsBoardApi.dlPortfolio(period),
  });
  if (!data) return null;
  const leads = data.leads;
  const placements = leads.reduce((n, l) => n + l.placements, 0);
  const requests = leads.reduce((n, l) => n + l.requests, 0);
  const openJobs = leads.reduce(
    (n, l) => n + l.clients.reduce((m, c) => m + c.open_jobs, 0),
    0,
  );
  const onTarget = leads.filter((l) => l.target_achieved).length;
  const assessed = leads.filter((l) => l.target_achieved !== null).length;
  return (
    <div className="grid grid-cols-1 gap-4 min-[420px]:grid-cols-2 md:grid-cols-4">
      <KpiCard
        label="Placementy"
        value={count(placements)}
        sub={`${count(requests)} zapytań`}
        icon={Users}
        color="blue"
      />
      <KpiCard
        label="Hit ratio (agregat)"
        value={requests > 0 ? pct((placements / requests) * 100) : "—"}
        sub="Suma placementów ÷ suma zapytań"
        icon={Award}
        color="green"
      />
      <KpiCard
        label="Otwarte rekrutacje"
        value={count(openJobs)}
        sub="stan na teraz"
        icon={Briefcase}
        color="indigo"
      />
      <KpiCard
        label={`DL w celu (≥ ${data.hit_ratio_target_pct}%)`}
        value={`${onTarget} / ${assessed}`}
        sub="DL z policzalnym hit ratio"
        icon={Trophy}
        color="orange"
      />
    </div>
  );
}
