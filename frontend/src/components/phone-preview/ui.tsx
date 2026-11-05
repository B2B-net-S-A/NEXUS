"use client";

import type { UseQueryResult } from "@tanstack/react-query";

import { Skeleton } from "@/components/ui/skeleton";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

export const count = (v: number | null | undefined) =>
  v == null ? "—" : Math.round(v).toLocaleString("pl-PL");

export const percent = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toLocaleString("pl-PL", { maximumFractionDigits: 1 })}%`;

export const hhmm = (at: string | number) =>
  new Date(at).toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Warsaw",
  });

export const plDate = (at: string) =>
  new Date(at).toLocaleDateString("pl-PL", { timeZone: "Europe/Warsaw" });

export function PageHeader({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) {
  return (
    <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b bg-card px-4 py-3">
      <div className="min-w-0">
        <h1 className="truncate text-xl font-semibold leading-tight">{title}</h1>
        {sub ? <p className="truncate text-xs text-muted-foreground">{sub}</p> : null}
      </div>
      {right}
    </header>
  );
}

export function Block({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="px-4 pt-5">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {note ? <span className="shrink-0 text-xs text-muted-foreground">{note}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function Delta({ pct, suffix }: { pct: number | null | undefined; suffix?: string }) {
  if (pct == null) return <span className="text-xs text-muted-foreground">bez porównania</span>;
  const up = pct >= 0;
  return (
    <span className={cn("text-xs font-medium", up ? "text-success-muted-foreground" : "text-destructive-muted-foreground")}>
      {up ? "▲" : "▼"} {percent(Math.abs(pct))}
      {suffix ? ` ${suffix}` : ""}
    </span>
  );
}

export function Hint({ children }: { children: React.ReactNode }) {
  return <span className="text-xs text-muted-foreground">{children}</span>;
}

export function Kpi({ label, value, foot }: { label: string; value: string; foot?: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl border bg-card p-3">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {foot ? <div className="mt-0.5 truncate">{foot}</div> : null}
    </div>
  );
}

export function Rows({ children }: { children: React.ReactNode }) {
  return <div className="divide-y rounded-xl border bg-card">{children}</div>;
}

export function Row({ label, value }: { label: React.ReactNode; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
      <span className="min-w-0 truncate">{label}</span>
      <span className="shrink-0 tabular-nums">{value}</span>
    </div>
  );
}

export function Progress({ label, current, target, suffix, behind }: {
  label: string;
  current: number | null;
  target: number | null;
  suffix?: string;
  behind?: boolean;
}) {
  const pct = current != null && target ? Math.min(100, (current / target) * 100) : 0;
  return (
    <div className="py-2.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span>{label}</span>
        <span className="tabular-nums">
          <b>{count(current)}</b>
          <span className="text-muted-foreground"> / {count(target)}{suffix ?? ""}</span>
        </span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", behind ? "bg-warning" : "bg-primary")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const x = (i: number) => (i / (values.length - 1)) * 340 + 6;
  const y = (v: number) => 70 - ((v - min) / (max - min || 1)) * 60;
  const points = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return (
    <svg viewBox="0 0 352 80" className="w-full" role="img" aria-label={label}>
      <polygon points={`6,76 ${points} 346,76`} className="fill-primary/10" />
      <polyline points={points} fill="none" strokeWidth="2.5" strokeLinejoin="round" className="stroke-primary" />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="4" className="fill-primary" />
    </svg>
  );
}

export function Bars({ rows }: { rows: Array<{ label: string; value: number; partial?: boolean }> }) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="flex items-end gap-1.5">
      {rows.map((r) => (
        <div key={r.label} className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <span className="text-xs tabular-nums text-muted-foreground">{r.value}</span>
          <div className={cn("w-full rounded-t", r.partial ? "bg-primary/40" : "bg-primary")} style={{ height: `${(r.value / max) * 56 + 2}px` }} />
          <span className="text-xs text-muted-foreground">{r.label}</span>
        </div>
      ))}
    </div>
  );
}

/**
 * Trzy stany jednej sekcji. Awaria zapytania nigdy nie wygląda jak zero ani
 * pusta lista (`empty-state-must-hang-on-issuccess`), a każda sekcja ładuje się
 * osobno, bo `in-flight/me` potrafi odpowiadać kilka sekund.
 */
export function Loaded<T>({ query, height = "h-24", children }: {
  query: UseQueryResult<T>;
  height?: string;
  children: (data: T) => React.ReactNode;
}) {
  if (query.isSuccess) return <>{children(query.data)}</>;
  if (query.isError) {
    return (
      <div className="rounded-xl border bg-card p-3 text-sm" role="alert">
        <p className="text-destructive-muted-foreground">{apiErrorMessage(query.error, "Nie udało się pobrać danych.")}</p>
        <button type="button" onClick={() => void query.refetch()} className="mt-2 h-10 font-medium text-primary">
          Spróbuj ponownie
        </button>
      </div>
    );
  }
  return <Skeleton className={cn("w-full rounded-xl", height)} />;
}
