"use client";

import { Fragment } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useSalesKpi, type KpiCell, type SalesKpi } from "@/lib/api/sales";
import { CALM_HEAD } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import { formatDealAmount, formatDealNumber } from "./format";
import {
  goalPercent,
  hasStageHistory,
  KPI_METRICS,
  LIGHT_LABEL,
  LIGHT_TONE,
  longDate,
  mrrPoints,
  shortDate,
} from "./kpi";

/**
 * Sprzedaż → Podsumowanie: KPI tygodniowe handlowców (8 tygodni, światła
 * względem celu) i krzywa WON netto MRR względem celu firmy. Definicje 1:1
 * z Atlasa, liczone w API (`services/sales/kpi.py`); „Oferty” to wejścia na
 * etap „Oferta wysłana”, bo NEXUS nie ma ofert (decyzja 28.10.2026).
 */
export function SalesKpiPanel() {
  const kpi = useSalesKpi(8);
  const state = resolveViewState({ isLoading: kpi.isLoading, error: kpi.error, isSuccess: kpi.isSuccess });

  if (state === "loading") return <p className="py-6 text-sm text-muted-foreground">Wczytywanie KPI…</p>;
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void kpi.refetch()} />;
  }
  if (!kpi.data) return null;
  return (
    <div className="space-y-4">
      <WeeklyTable data={kpi.data} />
      <WonMrrCard company={kpi.data.company} />
    </div>
  );
}

function KpiValue({ cell, noData = false }: { cell: KpiCell; noData?: boolean }) {
  if (noData) {
    return (
      <span className="text-xs text-muted-foreground" title="Przed startem historii etapów — brak danych">
        —
      </span>
    );
  }
  if (!cell.light) {
    return <span className="text-xs tabular-nums text-muted-foreground">{cell.actual}</span>;
  }
  return (
    <span title={`${cell.actual} z ${cell.target} — ${LIGHT_LABEL[cell.light]}`}>
      <StatusDot tone={LIGHT_TONE[cell.light]} className="tabular-nums">
        {cell.actual}
      </StatusDot>
    </span>
  );
}

function WeeklyTable({ data }: { data: SalesKpi }) {
  const current = data.weeks.length - 1;
  return (
    <Card className="min-w-0 p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">KPI tygodniowe</h2>
        <p className="text-xs text-muted-foreground">
          Zielone ≥ cel, żółte ≥ połowa celu, czerwone poniżej. Tygodnie od poniedziałku.
          {data.offers_history_since
            ? ` „Oferty (etap)” liczone od ${longDate(data.offers_history_since)}.`
            : " „Oferty (etap)” liczą się od pierwszego ruchu szansy po wdrożeniu."}
        </p>
      </div>
      {data.people.length === 0 ? (
        <EmptyState
          title="Brak handlowców z celami i wynikami"
          description="Administrator ustawia cele w oknie „Cele”; osoby ze spotkaniami albo leadami pojawią się tu same."
        />
      ) : (
        <div className="overflow-x-auto">
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Osoba</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Cel / tydz.</TableHead>
                {data.weeks.map((week, index) => (
                  <TableHead
                    key={week.start}
                    className={`${CALM_HEAD} text-right ${index === current ? "text-foreground" : ""}`}
                  >
                    <span className="block">T{week.iso_week}</span>
                    <span className="block text-[11px] font-normal">{shortDate(week.start)}</span>
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.people.map((person) => {
                const percent = goalPercent(person.margin_actual, person.margin_goal_amount);
                return (
                  <Fragment key={person.user_id}>
                    <TableRow className="border-t border-border bg-muted/40 hover:bg-muted/40">
                      <TableCell colSpan={data.weeks.length + 2} className="py-1.5">
                        <span className="text-sm font-semibold text-foreground">{person.name}</span>
                        {person.team ? <span className="ml-2 text-xs text-muted-foreground">{person.team}</span> : null}
                        {!person.has_targets ? <span className="ml-2 text-xs text-muted-foreground">bez celów</span> : null}
                        {percent !== null ? (
                          <span className="ml-3 text-xs text-muted-foreground">
                            Marża: {formatDealAmount(person.margin_actual)} z {formatDealAmount(person.margin_goal_amount)} ({percent}%)
                            {person.margin_goal_deadline ? ` do ${longDate(person.margin_goal_deadline)}` : ""}
                          </span>
                        ) : null}
                      </TableCell>
                    </TableRow>
                    {KPI_METRICS.map((metric) => (
                      <TableRow key={metric.key} className="hover:bg-transparent">
                        <TableCell className="py-1 pl-6 text-xs text-muted-foreground" title={metric.hint}>
                          {metric.label}
                        </TableCell>
                        <TableCell className="py-1 text-right text-xs tabular-nums text-muted-foreground">
                          {person.targets[metric.key] || "—"}
                        </TableCell>
                        {person.weeks.map((week, index) => (
                          <TableCell key={data.weeks[index].start} className="py-1 text-right">
                            <KpiValue
                              cell={week[metric.key]}
                              noData={
                                metric.key === "offers_stage" &&
                                !hasStageHistory(data.weeks[index].start, data.offers_history_since)
                              }
                            />
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </Card>
  );
}

function WonMrrCard({ company }: { company: SalesKpi["company"] }) {
  const points = mrrPoints(company.months, 12);
  const goal = Number(company.net_mrr_goal) || 0;
  const percent = goalPercent(company.won_net_mrr, company.net_mrr_goal);
  return (
    <Card className="min-w-0 p-4">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-foreground">WON netto MRR względem celu firmy</h2>
        <p className="text-sm tabular-nums text-foreground">
          {formatDealAmount(company.won_net_mrr)}
          {percent !== null ? (
            <span className="text-muted-foreground">
              {" "}
              z {formatDealAmount(company.net_mrr_goal)} ({percent}%)
              {company.goal_deadline ? ` do ${longDate(company.goal_deadline)}` : ""}
            </span>
          ) : (
            <span className="text-muted-foreground"> · cel firmy nieustawiony</span>
          )}
        </p>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        Wygrane szanse bez body leasingu, netto = MRR × marża, narastająco po miesiącu wygranej (jak w Atlasie).
        {company.missing_margin > 0
          ? ` ${company.missing_margin} wygranych z MRR nie ma marży — liczą się jako 0.`
          : ""}
      </p>
      {points.length === 0 ? (
        <p className="py-6 text-sm text-muted-foreground">Nie ma jeszcze wygranych szans z MRR.</p>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 10, right: 16, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
              <YAxis
                tick={{ fontSize: 11 }}
                stroke="hsl(var(--muted-foreground))"
                tickFormatter={(value: number) => formatDealNumber(value)}
                domain={[0, (max: number) => Math.max(max, goal) * 1.05]}
                width={64}
              />
              <Tooltip
                formatter={(value) => [formatDealAmount(Number(value)), "Netto MRR narastająco"]}
                contentStyle={{
                  background: "hsl(var(--popover))",
                  border: "1px solid hsl(var(--border))",
                  fontSize: 12,
                }}
              />
              {goal > 0 ? (
                <ReferenceLine
                  y={goal}
                  stroke="hsl(var(--warning))"
                  strokeDasharray="6 4"
                  label={{ value: "Cel firmy", position: "insideTopLeft", fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                />
              ) : null}
              <Line type="monotone" dataKey="cumulative" stroke="hsl(var(--primary))" strokeWidth={2} dot={{ r: 2 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
