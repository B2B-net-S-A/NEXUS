"use client";

import { useQuery } from "@tanstack/react-query";

import { kpisApi } from "@/lib/api";
import { insightsApi, insightsBoardApi, insightsQueryKeys } from "@/lib/insights-api";
import { racesApi } from "@/lib/insights-races-api";
import { useAuthStore } from "@/store/auth";

import { Block, Hint, Kpi, Loaded, Row, Rows, count, percent } from "./ui";

const TOP_CLIENTS = 5;
const QUARTER = { period: "quarter" } as const;

function LeagueBlock() {
  const league = useQuery({ queryKey: ["insights", "me", "league"], queryFn: () => racesApi.myLeague() });
  return (
    <Block title={`Liga ${league.data?.period ?? ""}`} note={league.data ? `zostało ${league.data.days_remaining} dni` : undefined}>
      <Loaded query={league} height="h-20">
        {(l) => {
          const s = l.standing;
          if (!s) return <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Nie bierzesz udziału w tej Lidze.</p>;
          const isDl = l.kind === "delivery_lead";
          return (
            <div className="rounded-xl border bg-card p-3 text-sm">
              <div className="flex items-baseline justify-between gap-3">
                <span>{s.rank != null ? `${s.rank}. miejsce z ${l.total}` : `${count(s.position_by_value)}. wg wyniku z ${l.total}, bez kwalifikacji`}</span>
                <b className="shrink-0 tabular-nums">{isDl ? percent(s.value) : `${count(s.value)} pkt`}</b>
              </div>
              {!s.me?.qualified && l.dl ? (
                <p className="mt-1 text-xs text-warning-muted-foreground">
                  Do kwalifikacji brakuje. Placementy: {l.dl.missing_placements}, zamknięte requesty: {l.dl.missing_closed_requests}
                </p>
              ) : null}
              {!s.me?.qualified && !l.dl && s.me ? (
                <p className="mt-1 text-xs text-warning-muted-foreground">
                  Do kwalifikacji potrzeba placementów: {l.required_placements}, masz: {s.me.placements}
                </p>
              ) : null}
              {!isDl && s.gap_to_podium ? <p className="mt-1 text-xs text-muted-foreground">Do podium: {count(s.gap_to_podium)} pkt</p> : null}
            </div>
          );
        }}
      </Loaded>
    </Block>
  );
}

function PeopleInFlightBlock() {
  const flight = useQuery({ queryKey: insightsQueryKeys.inFlightMe("mine"), queryFn: () => insightsApi.inFlightMe("mine") });
  return (
    <Block title="Moi ludzie w toku" note={flight.data ? `kolor: bez ruchu ${flight.data.stale_days}+ dni` : undefined}>
      <Loaded query={flight} height="h-40">
        {(f) => (
          <Rows>
            {f.columns.map((c) => (
              <Row
                key={c.column}
                label={c.label}
                value={<><b>{c.count}</b>{c.stale_count ? <span className="text-warning-muted-foreground"> · {c.stale_count}</span> : null}</>}
              />
            ))}
          </Rows>
        )}
      </Loaded>
    </Block>
  );
}

/** Rekruter: to samo źródło co „Mój miesiąc” w Insights (`/api/kpis/me/panel`). */
export function MyMonthSection() {
  const panel = useQuery({ queryKey: ["insights", "me", "panel"], queryFn: () => kpisApi.myPanel().then((r) => r.data) });
  return (
    <>
      <div className="px-4 pt-4">
        <Loaded query={panel} height="h-48">
          {(p) => (
            <div className="grid grid-cols-2 gap-2">
              <Kpi label="Placementy w miesiącu" value={count(p.placementy_month)} foot={<Hint>cel {count(p.target_placements_monthly)}</Hint>} />
              <Kpi label="Weryfikacje dziś" value={count(p.weryfikacje.day)} foot={<Hint>cel {count(p.target_verifications_daily)} · tydzień {count(p.weryfikacje.week)}</Hint>} />
              <Kpi label="Rekomendacje w tyg." value={count(p.rekomendacje.week)} foot={<Hint>miesiąc {count(p.rekomendacje.month)}</Hint>} />
              <Kpi label="Precyzja, 30 dni" value={percent(p.precision.value_pct)} foot={<Hint>cel {count(p.target_precision_pct)}%</Hint>} />
            </div>
          )}
        </Loaded>
      </div>
      <LeagueBlock />
      <PeopleInFlightBlock />
    </>
  );
}

/** Delivery Lead: „Moi klienci” jak w Insights, kwartał, definicja hit ratio z Portfeli DL. */
export function MyPortfolioSection() {
  const meId = useAuthStore((s) => s.user?.id);
  const portfolio = useQuery({ queryKey: insightsQueryKeys.dlPortfolio(QUARTER), queryFn: () => insightsBoardApi.dlPortfolio(QUARTER) });
  return (
    <>
      <div className="px-4 pt-4">
        <Loaded query={portfolio} height="h-48">
          {(p) => {
            const lead = p.leads.find((x) => x.dl_id === meId);
            if (!lead) return <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">W tym kwartale nie masz jeszcze klientów w portfelu.</p>;
            const clients = [...lead.clients].sort((a, b) => (b.open_jobs ?? 0) - (a.open_jobs ?? 0)).slice(0, TOP_CLIENTS);
            return (
              <div className="space-y-5">
                <div className="grid grid-cols-3 gap-2">
                  <Kpi label="Placementy" value={count(lead.placements)} foot={<Hint>kwartał</Hint>} />
                  <Kpi label="Hit ratio" value={percent(lead.hit_ratio)} foot={<Hint>cel {count(p.hit_ratio_target_pct)}%</Hint>} />
                  <Kpi label="Otwarte" value={count(lead.open_requests)} foot={<Hint>requesty</Hint>} />
                </div>
                <div>
                  <div className="mb-2 flex items-baseline justify-between gap-3">
                    <h2 className="text-sm font-semibold">Moi klienci</h2>
                    <Hint>otwarte · placementy</Hint>
                  </div>
                  <Rows>
                    {clients.map((x) => (
                      <Row key={x.client_id} label={x.client_name} value={<><b>{count(x.open_jobs)}</b> · {count(x.placements)}</>} />
                    ))}
                  </Rows>
                </div>
              </div>
            );
          }}
        </Loaded>
      </div>
      <LeagueBlock />
      <PeopleInFlightBlock />
    </>
  );
}
