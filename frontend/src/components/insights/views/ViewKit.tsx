"use client";

import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Delta } from "@/lib/insights-views";

/**
 * Wspólne klocki widoków Insights (przebudowa 24.09.2026).
 *
 * Każdy widok ma ten sam szkielet: pytanie w nagłówku, najwyżej cztery
 * kafle z punktem odniesienia, panele z JEDNYM wnioskiem zdaniem. Klocki są
 * tu, żeby cztery widoki nie rozjechały się wizualnie przy pierwszej zmianie.
 */

export function ViewHeader({
  question,
  lede,
  actions,
}: {
  question: string;
  lede?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
      <div className="min-w-0 space-y-1">
        <h2 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">
          {question}
        </h2>
        {lede ? (
          <div className="max-w-3xl text-sm text-muted-foreground">{lede}</div>
        ) : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </div>
  );
}

const TONE_CLASS: Record<Delta["tone"], string> = {
  good: "text-success-muted-foreground",
  bad: "text-warning-muted-foreground",
  neutral: "text-muted-foreground",
};

export function Tile({
  label,
  value,
  unit,
  reference,
  delta,
  progress,
  note,
}: {
  label: string;
  /** Gotowy napis; „—" dla brakujących danych („nie policzono", nie 0). */
  value: string;
  unit?: string;
  /** Punkt odniesienia obok liczby: „cel: 4", „średnia zespołu: 8". */
  reference?: string | null;
  delta?: Delta | null;
  /** 0–100; `null`/brak = bez paska. */
  progress?: number | null;
  note?: string | null;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-xl border border-border bg-card p-4 shadow-xs">
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-3xl font-semibold tabular-nums text-foreground">
          {value}
        </span>
        {unit ? (
          <span className="text-sm text-muted-foreground">{unit}</span>
        ) : null}
        {reference ? (
          <span className="text-sm text-muted-foreground">{reference}</span>
        ) : null}
      </p>
      {progress != null ? (
        <div
          className="h-1.5 rounded-full bg-muted"
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(Math.min(progress, 100))}
        >
          <div
            className="h-1.5 rounded-full bg-primary"
            style={{ width: `${Math.max(0, Math.min(progress, 100))}%` }}
          />
        </div>
      ) : null}
      {delta ? (
        <p className={cn("text-xs font-semibold", TONE_CLASS[delta.tone])}>
          {delta.text}
        </p>
      ) : null}
      {note ? <p className="text-xs text-muted-foreground">{note}</p> : null}
    </div>
  );
}

export function TileRow({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-4">
      {children}
    </div>
  );
}

export function Panel({
  title,
  hint,
  actions,
  children,
  className,
}: {
  title: string;
  hint?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col gap-4 rounded-xl border border-border bg-card p-4 shadow-xs sm:p-5",
        className,
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        {hint ? (
          <span className="text-xs text-muted-foreground">{hint}</span>
        ) : null}
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Jedno zdanie wniosku pod wykresem albo lejkiem. */
export function Takeaway({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-lg border border-warning/25 bg-warning-muted px-3 py-2.5 text-sm leading-relaxed text-warning-muted-foreground">
      {children}
    </p>
  );
}

export function PanelLoading() {
  return (
    <div className="flex items-center justify-center py-10">
      <Loader2
        className="h-5 w-5 animate-spin text-muted-foreground"
        aria-label="Ładowanie"
      />
    </div>
  );
}

/** Poziomy pasek lejka: etykieta, pasek, liczba, % przejścia. */
export function FunnelBars({
  steps,
  highlight,
}: {
  steps: { label: string; count: number; conversion: number | null }[];
  /** Indeks kroku do wyróżnienia (najsłabsze przejście). */
  highlight?: number | null;
}) {
  const max = Math.max(1, ...steps.map((s) => s.count));
  return (
    <ol className="space-y-2">
      {steps.map((step, i) => (
        <li
          key={step.label}
          className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_3.5rem_3.5rem] items-center gap-3 text-sm"
        >
          <span
            className={cn(
              "truncate text-foreground",
              i === highlight && "font-semibold",
            )}
          >
            {step.label}
          </span>
          <span className="h-4 rounded bg-muted">
            <span
              className="block h-4 rounded bg-primary"
              style={{ width: `${(100 * step.count) / max}%` }}
            />
          </span>
          <span className="text-right font-semibold tabular-nums text-foreground">
            {step.count.toLocaleString("pl-PL")}
          </span>
          <span
            className={cn(
              "text-right tabular-nums",
              i === highlight
                ? "font-bold text-warning-muted-foreground"
                : "text-muted-foreground",
            )}
          >
            {step.conversion === null ? "" : `${step.conversion}%`}
          </span>
        </li>
      ))}
    </ol>
  );
}
