"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";

import { useDlSendQueue } from "@/lib/api/boardTasks";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { racesApi } from "@/lib/insights-races-api";
import { pluralPl } from "@/lib/plural-pl";
import { reportHref } from "@/lib/insights-reports";
import { useAuthStore } from "@/store/auth";
import { SectionError } from "@/components/insights/sections/_shared";

import { Panel, PanelLoading, ViewHeader } from "../ViewKit";
import { MyBonusPanel } from "./MyBonusPanel";
import { MyGoalsPanel } from "./MyGoalsPanel";
import { MyInFlightPanel } from "./MyInFlightPanel";

/** Cele DL, Liga DL i hit ratio liczą kwartał — portfel też. */
const QUARTER: InsightsPeriodParams = { period: "quarter", offset: 0 };

function pct(value: number | null): string {
  return value === null ? "—" : `${Math.round(value)}%`;
}

/**
 * „Mój miesiąc” Delivery Leada (22.10.2026). Do tej pory DL widział ekran
 * rekrutera z celami rekrutera; jego cele to placementy portfela, hit ratio
 * i zamknięte rekrutacje w kwartale, a praca — kolejka do wysłania,
 * akceptacje i klienci.
 */
export function MyPortfolioView() {
  const meId = useAuthStore((state) => state.user?.id ?? null);
  const sendQueue = useDlSendQueue(true);
  const league = useQuery({
    queryKey: ["insights", "me", "position", "quarterly_champions_dl"],
    queryFn: () => racesApi.myPosition("quarterly_champions_dl"),
    staleTime: 5 * 60 * 1000,
  });
  const portfolio = useQuery({
    queryKey: insightsQueryKeys.dlPortfolio(QUARTER),
    queryFn: () => insightsBoardApi.dlPortfolio(QUARTER),
    staleTime: 5 * 60 * 1000,
  });
  const mine = portfolio.data?.leads.find((lead) => lead.dl_id === meId) ?? null;


  return (
    <div className="space-y-6">
      <ViewHeader
        question="Jak idzie mój portfel?"
        lede="Cele, Liga DL i hit ratio liczą bieżący kwartał — tak jak licznik celów w górnym pasku."
      />

      <MyGoalsPanel title="Moje cele w kwartale" />

      <MyInFlightPanel
        scope="portfolio"
        note={
          sendQueue.data ? (
            <>
              Do wysłania do klienta: <strong>{sendQueue.data.ready_total}</strong>{" "}
              {pluralPl(sendQueue.data.ready_total, "gotowe CV", "gotowe CV", "gotowych CV")}{" "}
              (kolejka z górnego paska).
            </>
          ) : null
        }
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Liga Mistrzów DL" hint="kwartał">
          {league.isPending ? (
            <p className="text-sm text-muted-foreground">Wczytuję…</p>
          ) : league.isError ? (
            <SectionError
              label="Liga DL"
              error={league.error}
              onRetry={() => void league.refetch()}
            />
          ) : league.data?.me ? (
            <p className="text-sm text-foreground">
              {league.data.rank ? (
                <strong>{league.data.rank}. miejsce</strong>
              ) : (
                <strong>bez miejsca w klasyfikacji</strong>
              )}{" "}
              · {league.data.me.metric_value} plac. w kwartale (z {league.data.total} DL)
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">
              Nie ma Cię jeszcze w rankingu tego kwartału.
            </p>
          )}
          <Link
            href="/insights?tab=rywalizacja"
            className="w-fit text-sm font-semibold text-primary hover:underline"
          >
            Cała rywalizacja →
          </Link>
        </Panel>
        <MyBonusPanel />
      </div>

      <Panel title="Moi klienci — kwartał" hint="ta sama definicja co raport „Portfele DL”">
        {portfolio.isPending ? (
          <PanelLoading />
        ) : portfolio.isError ? (
          <SectionError
            label="Moi klienci"
            error={portfolio.error}
            onRetry={() => void portfolio.refetch()}
          />
        ) : !mine || mine.clients.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nie masz w tym kwartale rekrutacji u przypisanych klientów.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="py-2 pr-3 text-left font-semibold">Klient</th>
                  <th className="py-2 pr-3 text-right font-semibold">Otwarte rekrutacje</th>
                  <th className="py-2 pr-3 text-right font-semibold">Placementy</th>
                  <th className="py-2 text-right font-semibold">
                    Hit ratio <span className="font-normal">cel {portfolio.data.hit_ratio_target_pct}%</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {mine.clients.map((c) => (
                  <tr key={c.client_id ?? c.client_name} className="border-b border-border/60">
                    <td className="py-2 pr-3 text-foreground">{c.client_name}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{c.open_jobs}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{c.placements}</td>
                    <td className="py-2 text-right tabular-nums">{pct(c.hit_ratio)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Link
          href={reportHref("portfele-dl", QUARTER)}
          className="w-fit text-sm font-semibold text-primary hover:underline"
        >
          Raport „Portfele Delivery Leadów” →
        </Link>
      </Panel>
    </div>
  );
}
