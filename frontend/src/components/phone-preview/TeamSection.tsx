"use client";

import { useQuery } from "@tanstack/react-query";

import { insightsApi, insightsQueryKeys } from "@/lib/insights-api";
import { insightsTeamSignalsApi } from "@/lib/insights-team-api";
import { racesApi } from "@/lib/insights-races-api";

import { Bars, Block, Loaded, Progress, Row, Rows, count } from "./ui";

const WEEKS = 8;
const ATTENTION_ITEMS = 5;

/** Zespół: cele, tygodnie i „W toku” z zakładki Zespół, bez tabeli osób i bez kwot. */
export function TeamSection({ withAttention }: { withAttention: boolean }) {
  const goals = useQuery({ queryKey: insightsQueryKeys.teamGoals(), queryFn: () => insightsApi.teamGoals() });
  const trend = useQuery({ queryKey: insightsQueryKeys.weeklyTrend(WEEKS), queryFn: () => insightsApi.weeklyTrend(WEEKS) });
  const flight = useQuery({ queryKey: insightsQueryKeys.inFlight(), queryFn: () => insightsApi.inFlight() });
  const attention = useQuery({
    queryKey: ["insights", "team", "attention"],
    enabled: withAttention,
    queryFn: () => insightsTeamSignalsApi.attention(),
  });
  const league = useQuery({ queryKey: ["insights", "me", "league"], queryFn: () => racesApi.myLeague() });
  return (
    <>
      <Block title="Cele zespołu" note={goals.data?.people ? `${goals.data.people} osób` : undefined}>
        <Loaded query={goals} height="h-48">
          {(g) => (
            <div className="divide-y rounded-xl border bg-card px-3">
              {g.goals.map((x) => (
                <Progress key={x.goal_id} label={x.short_title_pl ?? x.title_pl} current={x.current} target={x.target} suffix={x.unit === "pct" ? "%" : ""} behind={x.state === "behind"} />
              ))}
            </div>
          )}
        </Loaded>
      </Block>
      <Block title="Weryfikacje tydzień do tygodnia" note="jaśniej: trwa">
        <Loaded query={trend} height="h-32">
          {(t) => (
            <div className="rounded-xl border bg-card p-3">
              <Bars
                rows={t.weeks.map((w) => ({
                  label: `${Number(w.week_start.slice(8))}.${w.week_start.slice(5, 7)}`,
                  value: w.counts.verified ?? 0,
                  partial: w.partial,
                }))}
              />
            </div>
          )}
        </Loaded>
      </Block>
      {withAttention ? (
        <Block title="Do uwagi">
          <Loaded query={attention} height="h-40">
            {(a) =>
              a.items.length === 0 ? (
                <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Nic nie wymaga uwagi.</p>
              ) : (
                <Rows>
                  {a.items.slice(0, ATTENTION_ITEMS).map((i) => (
                    <div key={i.kind} className="flex gap-3 px-3 py-2.5 text-sm">
                      <b className="w-7 shrink-0 text-right tabular-nums">{i.count}</b>
                      <span className="min-w-0">{i.label}</span>
                    </div>
                  ))}
                </Rows>
              )
            }
          </Loaded>
        </Block>
      ) : null}
      <Block title="W toku" note={flight.data?.forecast ? `prognoza z akceptacji: ${flight.data.forecast.low}–${flight.data.forecast.high}` : undefined}>
        <Loaded query={flight} height="h-40">
          {(f) => (
            <Rows>
              {f.columns.map((c) => <Row key={c.column} label={c.label} value={<b>{c.count}</b>} />)}
            </Rows>
          )}
        </Loaded>
      </Block>
      {league.data?.standing?.neighbours.length ? (
        <Block title={`Liga ${league.data.period}`} note="wokół Ciebie">
          <Rows>
            {league.data.standing.neighbours.map((n) => (
              <div key={n.user_id} className="flex items-center gap-3 px-3 py-2.5 text-sm">
                <span className="w-6 shrink-0 tabular-nums text-muted-foreground">{n.rank ?? "–"}</span>
                <span className="min-w-0 flex-1 truncate">{n.name}</span>
                <b className="shrink-0 tabular-nums">{count(n.metric_value)}</b>
              </div>
            ))}
          </Rows>
        </Block>
      ) : null}
    </>
  );
}
