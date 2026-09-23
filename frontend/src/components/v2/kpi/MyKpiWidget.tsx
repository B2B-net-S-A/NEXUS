"use client";

import { useState } from "react";
import { Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMyKpis } from "@/hooks/useMyKpis";
import { useMyGoals } from "@/hooks/useMyGoals";
import type { KpiGoal, KpiResult, KpiState, MyKpiGoals } from "@/lib/api";
import { KpiProgressBar } from "./KpiProgressBar";

interface Props {
  /** compact (topbar, 1 linia ikon + popover na hover) vs dashboard (siatka). */
  variant?: "compact" | "dashboard";
  className?: string;
}

/** Jeden wiersz widgetu — osobiste KPI i cele lidera w tym samym kształcie. */
interface WidgetRow {
  id: string;
  title: string;
  label: string;
  /** null = niepoliczony — wiersz bez paska postępu. */
  progressPct: number | null;
  state: KpiState | null;
  note?: string | null;
}

const PERIOD_ORDER: Record<string, number> = { day: 0, week: 1, month: 2, quarter: 3 };

function sortKpis(kpis: readonly KpiResult[]): KpiResult[] {
  return [...kpis].sort((a, b) => {
    const po = (PERIOD_ORDER[a.period] ?? 9) - (PERIOD_ORDER[b.period] ?? 9);
    if (po !== 0) return po;
    return a.kpi_id.localeCompare(b.kpi_id);
  });
}

function kpiRow(k: KpiResult): WidgetRow {
  return {
    id: k.kpi_id,
    title: k.title_pl,
    label: `${k.current}/${k.target}`,
    progressPct: k.progress_pct,
    state: k.state,
  };
}

function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

/** „3/6", „24.5%/30%" albo „niepoliczony" — nigdy „0" za brak danych. */
export function goalLabel(goal: KpiGoal): string {
  if (goal.current === null) return "niepoliczony";
  const suffix = goal.unit === "pct" ? "%" : "";
  return `${formatNumber(goal.current)}${suffix}/${formatNumber(goal.target)}${suffix}`;
}

function goalRow(goal: KpiGoal): WidgetRow {
  return {
    id: goal.goal_id,
    title: goal.title_pl,
    label: goalLabel(goal),
    progressPct: goal.progress_pct,
    state: goal.state,
    note: goal.note,
  };
}

function goalsHeading(goals: MyKpiGoals): string {
  if (goals.kind === "delivery_lead") return `Cele portfela · ${goals.scope_label}`;
  const people = goals.people ?? 0;
  return `Cele zespołu · osoby: ${people}`;
}

function stateEmoji(state: KpiState | null): string {
  switch (state) {
    case "hit":
    case "ahead":
      return "🎯";
    case "on_track":
      return "→";
    case "behind":
      return "↓";
    case "missed":
      return "×";
    default:
      return "·";
  }
}

function Row({ row, variant }: { row: WidgetRow; variant: "compact" | "full" }) {
  if (row.progressPct === null || row.state === null) {
    // Niepoliczony: bez paska — pusty pasek czytałby się jak wynik zero.
    return (
      <div className="flex flex-col gap-0.5 text-xs">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-foreground">{row.title}</span>
          <span className="text-muted-foreground">{row.label}</span>
        </div>
        {row.note ? <span className="text-muted-foreground">{row.note}</span> : null}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-0.5">
      <KpiProgressBar
        id={row.id}
        title={row.title}
        label={row.label}
        progressPct={row.progressPct}
        state={row.state}
        variant={variant}
      />
      {row.note && variant === "full" ? (
        <span className="text-xs text-muted-foreground">{row.note}</span>
      ) : null}
    </div>
  );
}

/**
 * „Moje KPI" — widget w TopbarV2 (wariant compact) i kafelek pulpitu.
 *
 * - Osobiste KPI (rekruter / sourcer / TAC) z `/api/kpis/me/today`.
 * - Cele liderów (22.09.2026) z `/api/kpis/me/goals`: Delivery Lead — portfel
 *   w kwartale, HoR / TCM — cele zespołu. „Niepoliczony" renderuje się
 *   tekstem, nigdy jako zero.
 * - Nic do pokazania → widget zwraca null.
 */
export function MyKpiWidget({ variant = "compact", className }: Props) {
  const kpisQuery = useMyKpis();
  const goalsQuery = useMyGoals();
  const [hovered, setHovered] = useState(false);

  const kpiRows = kpisQuery.isLoading || kpisQuery.error ? [] : sortKpis(kpisQuery.data ?? []).map(kpiRow);
  const goals =
    goalsQuery.data && goalsQuery.data.kind !== "none" && goalsQuery.data.goals.length > 0
      ? goalsQuery.data
      : null;
  const goalRows = goals ? goals.goals.map(goalRow) : [];

  if (kpiRows.length === 0 && goalRows.length === 0) return null;

  if (variant === "dashboard") {
    return (
      <section
        // `@container`: wariant „dashboard" żyje w kafelku (min. w=4 = 364 px
        // przy 1280) — liczba kolumn od szerokości kafelka, nie okna.
        className={cn("@container rounded-lg border border-border", "bg-card p-4", className)}
        aria-label="Moje KPI"
      >
        <header className="flex items-center gap-2 mb-3">
          <Target className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Twoje KPI</h2>
        </header>
        {kpiRows.length > 0 ? (
          <div className="grid grid-cols-1 @lg:grid-cols-2 @3xl:grid-cols-3 gap-4">
            {kpiRows.map((row) => (
              <Row key={row.id} row={row} variant="full" />
            ))}
          </div>
        ) : null}
        {goals ? (
          <div className={cn(kpiRows.length > 0 && "mt-4")}>
            <h3 className="text-xs font-semibold text-muted-foreground mb-2">
              {goalsHeading(goals)}
            </h3>
            <div className="grid grid-cols-1 @lg:grid-cols-2 @3xl:grid-cols-3 gap-4">
              {goalRows.map((row) => (
                <Row key={row.id} row={row} variant="full" />
              ))}
            </div>
          </div>
        ) : null}
      </section>
    );
  }

  // compact: 3 najważniejsze (osobiste przed celami lidera; day > week > month)
  const top = [...kpiRows, ...goalRows].slice(0, 3);

  return (
    <div
      className={cn("relative", className)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      // Szczegóły KPI także z klawiatury i dotykiem — do 09.2026 wyłącznie hover,
      // czyli niedostępne na tablecie i dla nawigacji tabulatorem.
      onFocus={() => setHovered(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setHovered(false);
        }
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") setHovered(false);
      }}
    >
      <button
        type="button"
        // Otwiera (nie przełącza): kliknięcie myszą najpierw ustawia fokus, więc
        // przełączanie zamykałoby właśnie otwarte szczegóły. Zamyka blur/Escape.
        onClick={() => setHovered(true)}
        aria-expanded={hovered}
        aria-describedby={hovered ? "my-kpi-tooltip" : undefined}
        className={cn(
          "flex items-center gap-2 h-9 px-3 rounded-lg",
          "border border-border",
          "bg-background/60 hover:bg-background",
          "text-xs text-muted-foreground transition-colors",
        )}
        aria-label="Moje KPI"
      >
        <Target className="h-3.5 w-3.5 text-primary shrink-0" />
        <span className="hidden xl:flex items-center gap-2">
          {top.map((row) => (
            <span key={row.id} className="flex items-center gap-1 tabular-nums" title={row.title}>
              <span className="shrink-0">{stateEmoji(row.state)}</span>
              <span className="font-medium text-foreground">{row.label}</span>
            </span>
          ))}
        </span>
        <span className="xl:hidden font-medium text-foreground">KPI</span>
      </button>

      {hovered && (
        <div
          className={cn(
            "absolute right-0 top-full mt-2 w-72 p-3 z-50",
            "rounded-lg border border-border",
            "bg-card shadow-smd",
          )}
          role="tooltip"
          id="my-kpi-tooltip"
        >
          {kpiRows.length > 0 ? (
            <>
              <div className="text-xs font-semibold text-foreground mb-2">
                Twoje KPI dziś / tydzień / miesiąc
              </div>
              <div className="flex flex-col gap-2.5">
                {kpiRows.map((row) => (
                  <Row key={row.id} row={row} variant="compact" />
                ))}
              </div>
            </>
          ) : null}
          {goals ? (
            <>
              <div className={cn("text-xs font-semibold text-foreground mb-2", kpiRows.length > 0 && "mt-3")}>
                {goalsHeading(goals)}
              </div>
              <div className="flex flex-col gap-2.5">
                {goalRows.map((row) => (
                  <Row key={row.id} row={row} variant="compact" />
                ))}
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
