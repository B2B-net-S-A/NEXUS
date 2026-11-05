"use client";

import { useQuery } from "@tanstack/react-query";

import { firmaSentence } from "@/lib/insights-firma";
import { insightsApi, insightsBoardApi, insightsQueryKeys } from "@/lib/insights-api";
import { monthForecast } from "@/lib/insights-in-flight";
import { compactPln } from "@/lib/insights-views";

import { Block, Delta, Hint, Kpi, Loaded, Row, Rows, Sparkline, count, percent, plDate } from "./ui";

export type CompanyPeriod = "month" | "quarter" | "year";

const HIDDEN = "•••";
const TOP_CLIENTS = 5;

/**
 * Wyniki firmy (admin, „Wyniki firmy”, Rada): te same trasy i to samo zdanie co
 * zakładka Firma. Kwoty domyślnie ukryte (decyzja Artura 05.11.2026), bo ekran
 * telefonu bywa widoczny dla innych; procenty i liczby sztuk zostają.
 */
export function CompanySection({ hidden, period }: { hidden: boolean; period: CompanyPeriod }) {
  const params = { period };
  const board = useQuery({ queryKey: insightsQueryKeys.board(params), queryFn: () => insightsBoardApi.board(params) });
  const flows = useQuery({ queryKey: insightsQueryKeys.boardFlows(params), queryFn: () => insightsBoardApi.boardFlows(params) });
  const ranking = useQuery({ queryKey: insightsQueryKeys.clientsRanking(params), queryFn: () => insightsBoardApi.clientsRanking(params) });
  const inFlight = useQuery({ queryKey: insightsQueryKeys.inFlight(), queryFn: () => insightsApi.inFlight() });
  const money = (v: number | null | undefined) => (hidden ? HIDDEN : compactPln(v));

  const data = board.data;
  const ongoing = data ? new Date(data.period.end).getTime() > Date.now() : false;
  const sentence = data
    ? firmaSentence({
        margin: hidden || data.kpis.finance.margin_monthly_pln === null ? null : compactPln(data.kpis.finance.margin_monthly_pln),
        marginChangePct: data.comparison.margin_monthly_pln.change_pct,
        net: flows.data?.consultants.net ?? null,
        endingWithoutContinuation: flows.data?.ending_without_continuation.contracts ?? null,
        periodForecast: ongoing && inFlight.data ? monthForecast(data.kpis.placements, inFlight.data.forecast) : null,
      })
    : null;

  return (
    <>
      <div className="px-4 pt-3">
        <Loaded query={board} height="h-64">
          {(b) => {
            const c = b.comparison;
            const months = b.trend.months.filter((m) => m.margin_monthly_pln !== null);
            return (
              <div className="space-y-3">
                {sentence ? <p className="text-sm leading-snug">{sentence}</p> : null}
                <div className="grid grid-cols-2 gap-2">
                  <Kpi label="Przychód / mc" value={money(b.kpis.finance.revenue_monthly_pln)} foot={<Delta pct={c.revenue_monthly_pln.change_pct} />} />
                  <Kpi label="Marża / mc" value={money(b.kpis.finance.margin_monthly_pln)} foot={<Delta pct={c.margin_monthly_pln.change_pct} />} />
                  <Kpi label="Pracujący konsultanci" value={count(b.kpis.finance.active_consultants)} foot={<Delta pct={c.active_consultants.change_pct} />} />
                  <Kpi label="Placementy" value={count(b.kpis.placements)} foot={<Delta pct={c.placements.change_pct} suffix={c.placements_previous_window?.same_stretch ? "ten sam odcinek" : undefined} />} />
                </div>
                <div className="rounded-xl border bg-card p-3">
                  <div className="mb-1 flex justify-between text-sm font-semibold"><span>Marża miesięczna</span><Hint>12 miesięcy</Hint></div>
                  <Sparkline values={months.map((m) => m.margin_monthly_pln as number)} label="Marża miesięczna, ostatnie 12 miesięcy" />
                  <div className="flex justify-between text-xs text-muted-foreground"><span>{months[0]?.label}</span><span>{months[months.length - 1]?.label}</span></div>
                </div>
              </div>
            );
          }}
        </Loaded>
      </div>
      <Block title="Ruch konsultantów" note={flows.data ? `od ${plDate(flows.data.window.from)}` : undefined}>
        <Loaded query={flows}>
          {(f) => (
            <div className="space-y-2">
              <div className="grid grid-cols-3 gap-2">
                <Kpi label="Przyszli" value={`+${count(f.consultants.starts)}`} />
                <Kpi label="Odeszli" value={`−${count(f.consultants.ends)}`} foot={<Hint>rezygnacje {f.consultants.resignations}</Hint>} />
                <Kpi label="Netto" value={`${f.consultants.net >= 0 ? "+" : "−"}${count(Math.abs(f.consultants.net))}`} />
              </div>
              <p className="rounded-xl border bg-card p-3 text-sm">
                <b className="tabular-nums">{count(f.ending_without_continuation.contracts)}</b> kontraktów kończy się w {f.ending_without_continuation.days} dni bez kontynuacji
              </p>
              <div className="grid grid-cols-2 gap-2">
                <Kpi label="Otwarte rekrutacje" value={count(f.jobs.open)} foot={<Hint>{count(f.jobs.open_clients)} klientów</Hint>} />
                <Kpi label="Hit ratio (zamknięte)" value={percent(board.data?.kpis.hit_ratio_pct)} foot={<Hint>{count(board.data?.kpis.jobs_closed_with_placement)} z {count(board.data?.kpis.jobs_closed)}</Hint>} />
              </div>
            </div>
          )}
        </Loaded>
      </Block>
      <Block title="Najwięksi klienci" note="marża / mc">
        <Loaded query={ranking}>
          {(r) => (
            <Rows>
              {[...r.clients]
                .filter((x) => x.monthly_margin_total !== null)
                .sort((a, b) => (b.monthly_margin_total ?? 0) - (a.monthly_margin_total ?? 0))
                .slice(0, TOP_CLIENTS)
                .map((x) => (
                  <Row key={x.client_id} label={x.name} value={<b>{money(x.monthly_margin_total)}</b>} />
                ))}
            </Rows>
          )}
        </Loaded>
      </Block>
      {data?.degraded?.message ? <p className="px-4 pt-3 text-xs text-muted-foreground">{data.degraded.message}</p> : null}
    </>
  );
}
