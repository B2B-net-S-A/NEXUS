"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsClientFunnelResponse,
  type InsightsClientFunnelRow,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { formatIsoDatePl } from "@/lib/date-pl";
import { warsawDateOf } from "@/lib/warsaw-date";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";
import { count, DefinitionNote, pct } from "./InsightsFormat";

interface Props {
  period: InsightsPeriodParams;
}

const HEAD = "px-3 py-2 text-right font-medium";
const CELL = "px-3 py-2 text-right tabular-nums";

const days = (value: number | null): string =>
  value === null ? "—" : `${String(value).replace(".", ",")} d`;

const oneDecimal = (value: number | null): string =>
  value === null ? "—" : String(value).replace(".", ",");

/**
 * Udział największego klienta w CV i w zatrudnieniach — jedno zdanie nad tabelą.
 * Ma sens tylko przy co najmniej dwóch klientach i dowolnych zatrudnieniach.
 */
export function funnelLede(data: InsightsClientFunnelResponse): string | null {
  const [top] = data.clients;
  if (!top || data.clients.length < 2 || data.totals.cv_sent === 0 || data.totals.hires === 0) {
    return null;
  }
  const cvShare = Math.round((top.cv_sent / data.totals.cv_sent) * 100);
  const hireShare = Math.round((top.hires / data.totals.hires) * 100);
  return `${top.client_name} dostaje ${cvShare}% naszych CV i daje ${hireShare}% zatrudnień.`;
}

function HitRatioCell({
  row,
  target,
}: {
  row: Pick<InsightsClientFunnelRow, "won" | "lost" | "hit_ratio">;
  target: number;
}) {
  const decided = row.won + row.lost;
  if (row.hit_ratio === null) return <span className="text-muted-foreground">—</span>;
  return (
    <span className={cn(row.hit_ratio < target && "font-semibold text-destructive-muted-foreground")}>
      {pct(row.hit_ratio, 0)}{" "}
      <span className="font-normal text-muted-foreground">
        ({row.won}/{decided})
      </span>
    </span>
  );
}

/**
 * Tabela „Klienci” (audyt 08.11.2026, B3): lejek i hit ratio per klient.
 * Definicje mieszkają na serwerze (`services/insights_client_funnel.py`), ekran
 * tylko je pokazuje; zamknięcia „do przejrzenia” są osobną kolumną, bo nie są
 * ani wygraną, ani przegraną.
 */
export function InsightsClientFunnel({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.clientsFunnel(period),
    queryFn: () => insightsBoardApi.clientsFunnel(period),
  });
  const clients = data?.clients ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: clients.length === 0,
  });

  if (viewState === "loading") {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (isBlockingViewState(viewState)) {
    return <SectionError label="Klienci" error={error} onRetry={() => void refetch()} />;
  }
  if (viewState === "empty" || !data) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        W tym okresie nie ma CV, rozmów ani zamknięć u żadnego klienta.
      </p>
    );
  }

  const target = data.hit_ratio_target_pct;
  const lede = funnelLede(data);
  const { totals } = data;

  return (
    <section className="space-y-3">
      {lede ? <p className="text-sm font-medium text-foreground">{lede}</p> : null}
      <div className="max-h-[calc(100dvh-14rem)] overflow-auto rounded-xl border border-border bg-card">
        <table className="w-full min-w-[820px] text-sm" data-testid="client-funnel-table">
          <thead className="sticky top-0 z-10 bg-muted text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">Klient</th>
              <th scope="col" className={HEAD}>CV</th>
              <th scope="col" className={HEAD}>Rozmowy</th>
              <th scope="col" className={HEAD}>Zatrudnieni</th>
              <th scope="col" className={HEAD} title="Liczba CV na jedno zatrudnienie w tym okresie">
                CV na zatrudnienie
              </th>
              <th scope="col" className={HEAD} title="Wygrane / wygrane + przegrane">Hit ratio</th>
              <th scope="col" className={HEAD} title="Zamknięte bez powodu albo z powodem „Inny”">
                Do przejrzenia
              </th>
              <th scope="col" className={HEAD} title="Mediana dni od otwarcia do pierwszego CV">
                Pierwsze CV
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {clients.map((row) => (
              <tr key={row.client_id}>
                <td className="max-w-[16rem] truncate px-3 py-2 font-medium text-foreground" title={row.client_name}>
                  {row.client_name}
                </td>
                <td className={CELL}>{count(row.cv_sent)}</td>
                <td className={CELL}>{count(row.client_interviews)}</td>
                <td className={CELL}>{count(row.hires)}</td>
                <td className={CELL}>{oneDecimal(row.cv_per_hire)}</td>
                <td className={CELL}><HitRatioCell row={row} target={target} /></td>
                <td className={CELL}>{row.unreviewed > 0 ? count(row.unreviewed) : "—"}</td>
                <td className={CELL} title={`Rekrutacje z pierwszym CV w tym okresie: ${row.first_cv_jobs}`}>
                  {days(row.first_cv_median_days)}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot className="sticky bottom-0 bg-muted font-semibold">
            <tr>
              <td className="px-3 py-2">Razem</td>
              <td className={CELL}>{count(totals.cv_sent)}</td>
              <td className={CELL}>{count(totals.client_interviews)}</td>
              <td className={CELL}>{count(totals.hires)}</td>
              <td className={CELL}>{oneDecimal(totals.cv_per_hire)}</td>
              <td className={CELL}><HitRatioCell row={totals} target={target} /></td>
              <td className={CELL}>{totals.unreviewed > 0 ? count(totals.unreviewed) : "—"}</td>
              <td className={CELL}>—</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <DefinitionNote>
        CV, rozmowy i zatrudnienia to pierwsze wejście osoby na etap w wybranym okresie. Hit ratio
        liczymy z zamknięć od {formatIsoDatePl(warsawDateOf(data.hit_ratio_since) ?? data.hit_ratio_since.slice(0, 10))}: wygrane przez
        wygrane i przegrane (na czerwono poniżej {target}%). Zamknięte bez powodu i z powodem „Inny”
        są w kolumnie „Do przejrzenia” i nie obniżają wyniku.
      </DefinitionNote>
    </section>
  );
}
