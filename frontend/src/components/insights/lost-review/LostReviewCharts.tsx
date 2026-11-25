"use client";

/**
 * Wykresy zakładki „Przegrane” (25.11.2026). Kolory z tokenów: wygrane `--info`,
 * przegrane `--warning`, etapy przegranej od `--destructive` (bez CV) do `--success`
 * (po akceptacji) — ta sama kolejność co pasek etapów na kartach.
 */

import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  LOST_STAGES,
  plNumber,
  type LostReviewClient,
  type LostReviewCount,
  type LostReviewTrendMonth,
  type LostStage,
} from "@/lib/lost-review";
import { cn } from "@/lib/utils";

export const WON_COLOR = "hsl(var(--info))";
export const LOST_COLOR = "hsl(var(--warning))";
const AXIS_TICK = { fontSize: 11 } as const;
const AXIS_STROKE = "hsl(var(--muted-foreground))";
const GRID_STROKE = "hsl(var(--border))";

export const STAGE_TONE: Record<LostStage, string> = {
  no_cv: "bg-destructive",
  cv_only: "bg-warning",
  interview: "bg-info",
  acceptance: "bg-success",
};

export function Panel({
  title,
  lede,
  children,
  className,
}: {
  title: string;
  lede?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("min-w-0 rounded-xl border border-border bg-card p-4 shadow-xs", className)}>
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {lede ? <p className="mt-0.5 text-xs text-muted-foreground">{lede}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** Wygrane i przegrane per miesiąc z hit ratio na prawej osi. */
export function TrendChart({ months }: { months: LostReviewTrendMonth[] }) {
  if (months.length === 0) {
    return <p className="text-sm text-muted-foreground">Brak zamknięć w tym oknie.</p>;
  }
  return (
    <div className="h-52" data-testid="lost-review-trend">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={months} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} vertical={false} />
          <XAxis dataKey="label" tick={AXIS_TICK} stroke={AXIS_STROKE} />
          <YAxis yAxisId="n" allowDecimals={false} tick={AXIS_TICK} stroke={AXIS_STROKE} />
          <YAxis
            yAxisId="pct"
            orientation="right"
            domain={[0, 100]}
            tick={AXIS_TICK}
            stroke={AXIS_STROKE}
            unit="%"
          />
          <Tooltip
            formatter={(value: unknown, name: unknown) => [
              name === "Hit ratio" ? `${plNumber(value as number)}%` : String(value),
              String(name),
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar yAxisId="n" dataKey="won" name="Wygrane" fill={WON_COLOR} radius={[3, 3, 0, 0]} />
          <Bar yAxisId="n" dataKey="lost" name="Przegrane" fill={LOST_COLOR} radius={[3, 3, 0, 0]} />
          <Line
            yAxisId="pct"
            type="monotone"
            dataKey="hit_ratio"
            name="Hit ratio"
            stroke="hsl(var(--foreground))"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Pasek etapów przegranej z liczbami pod spodem. */
export function StageBar({ stages, total }: { stages: Record<LostStage, number>; total: number }) {
  return (
    <div data-testid="lost-review-stages">
      <div className="flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        {LOST_STAGES.map((s) =>
          stages[s.key] && total ? (
            <div
              key={s.key}
              className={STAGE_TONE[s.key]}
              style={{ width: `${(stages[s.key] / total) * 100}%` }}
            />
          ) : null,
        )}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {LOST_STAGES.map((s) => (
          <div key={s.key} className="min-w-0">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className={cn("size-2 shrink-0 rounded-full", STAGE_TONE[s.key])} />
              {s.label}
            </div>
            <div className="text-xl font-semibold tabular-nums text-foreground">{stages[s.key]}</div>
            <div className="text-xs text-muted-foreground">{s.hint}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Poziome paski z liczbą — „Co zdecydowało?” i oceny klienta. */
export function CountBars({
  items,
  empty,
  testId,
}: {
  items: LostReviewCount[];
  empty: string;
  testId: string;
}) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid={testId}>
        {empty}
      </p>
    );
  }
  const max = Math.max(...items.map((i) => i.count));
  return (
    <ul className="space-y-1.5" data-testid={testId}>
      {items.map((item) => (
        <li key={item.label} className="grid grid-cols-[minmax(0,11rem)_1fr_2rem] items-center gap-2 text-sm">
          <span className="truncate text-foreground" title={item.label}>
            {item.label}
          </span>
          <span className="h-2 rounded-full bg-muted">
            <span
              className="block h-2 rounded-full bg-primary"
              style={{ width: `${(item.count / max) * 100}%` }}
            />
          </span>
          <span className="text-right tabular-nums text-muted-foreground">{item.count}</span>
        </li>
      ))}
    </ul>
  );
}

/** Wygrane i przegrane klientów z największą liczbą zamknięć. */
export function ClientsChart({ clients }: { clients: LostReviewClient[] }) {
  const top = [...clients]
    .sort((a, b) => b.won + b.lost - (a.won + a.lost))
    .slice(0, 8)
    .map((c) => ({ name: c.name, won: c.won, lost: c.lost }));
  if (top.length === 0) {
    return <p className="text-sm text-muted-foreground">Brak zamknięć w tym okresie.</p>;
  }
  return (
    <div style={{ height: 28 * top.length + 40 }} data-testid="lost-review-clients-chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={top} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} horizontal={false} />
          <XAxis type="number" allowDecimals={false} tick={AXIS_TICK} stroke={AXIS_STROKE} />
          <YAxis
            type="category"
            dataKey="name"
            width={130}
            tick={AXIS_TICK}
            stroke={AXIS_STROKE}
            tickFormatter={(v: string) => (v.length > 18 ? `${v.slice(0, 17)}…` : v)}
          />
          <Tooltip />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="won" name="Wygrane" stackId="a" fill={WON_COLOR} />
          <Bar dataKey="lost" name="Przegrane" stackId="a" fill={LOST_COLOR} radius={[0, 3, 3, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
