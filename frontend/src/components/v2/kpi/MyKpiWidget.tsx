"use client";

import { useState } from "react";
import { Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useMyKpis } from "@/hooks/useMyKpis";
import { useMyGoals } from "@/hooks/useMyGoals";
import type { KpiGoal, KpiResult, KpiState, MyKpiGoals } from "@/lib/api";
import { KpiGoalsPanel } from "./KpiGoalsPanel";
import { KpiProgressBar } from "./KpiProgressBar";
import { KpiTopbarButton } from "./KpiTopbarButton";
import { buildKpiTopbarModel, formatKpiNumber, type KpiTopbarModel } from "./kpi-topbar-model";

interface Props {
  /** compact (topbar: podpisane segmenty + panel po kliknięciu) vs dashboard (siatka). */
  variant?: "compact" | "dashboard";
  className?: string;
}

/** Jeden wiersz kafelka — osobiste KPI i cele lidera w tym samym kształcie. */
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

/** „3/6", „24,5%/30%", sam wynik, gdy celu jeszcze nie ma, albo „niepoliczony" — nigdy „0" za brak danych. */
export function goalLabel(goal: KpiGoal): string {
  if (goal.current === null) return "niepoliczony";
  const suffix = goal.unit === "pct" ? "%" : "";
  const current = `${formatKpiNumber(goal.current)}${suffix}`;
  // Delivery Lead bez zamkniętych rekrutacji: wynik jest, celu nie ma („2", nie „2/0").
  if (goal.state === null || goal.target <= 0) return current;
  return `${current}/${formatKpiNumber(goal.target)}${suffix}`;
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

function Row({ row }: { row: WidgetRow }) {
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
        variant="full"
      />
      {row.note ? <span className="text-xs text-muted-foreground">{row.note}</span> : null}
    </div>
  );
}

/**
 * Licznik z segmentami i panel otwierany kliknięciem — bez zapytań, więc
 * harness `/preview/kpi-topbar` klika ten sam komponent co pasek.
 */
export function KpiTopbarPopover({
  model,
  className,
}: {
  model: KpiTopbarModel;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    // Opakowanie niesie `hidden md:block` z TopbarV2 — na przycisku z `flex`
    // klasa `md:block` rozbiłaby układ segmentów. `data-topbar-shrinks`: jedyny
    // element grupy akcji, który wolno ścisnąć (`shell/topbar-layout.ts`).
    <div className={className} data-topbar-shrinks="">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <KpiTopbarButton model={model} open={open} />
        </PopoverTrigger>
        <PopoverContent
          align="end"
          aria-label={model.panelTitle}
          className="w-[360px] overflow-hidden p-0"
        >
          <KpiGoalsPanel model={model} onNavigate={() => setOpen(false)} />
        </PopoverContent>
      </Popover>
    </div>
  );
}

/**
 * „Moje KPI" — licznik celów w TopbarV2 (wariant compact) i kafelek pulpitu.
 *
 * - Osobiste KPI rekrutera z `/api/kpis/me/today`.
 * - Cele liderów (22.09.2026) z `/api/kpis/me/goals`: Delivery Lead — 30% hit
 *   ratio portfela w kwartale, HoR / TCM — cele zespołu. „Niepoliczony" renderuje
 *   się tekstem, nigdy jako zero.
 * - Nic do pokazania → widget zwraca null.
 *
 * Wariant compact (13.10.2026): do trzech podpisanych segmentów i panel
 * otwierany KLIKNIĘCIEM. Do tego dnia były to trzy pary „znak + wynik/cel”
 * bez nazw, a szczegóły w dymku na najechanie. Układ i teksty liczy
 * `buildKpiTopbarModel`; reguły: docs/claude/ui/licznik-celow-w-gornym-pasku.md.
 */
export function MyKpiWidget({ variant = "compact", className }: Props) {
  const kpisQuery = useMyKpis();
  const goalsQuery = useMyGoals();

  const kpis = kpisQuery.isLoading || kpisQuery.error ? [] : (kpisQuery.data ?? []);
  const goals =
    goalsQuery.data && goalsQuery.data.kind !== "none" && goalsQuery.data.goals.length > 0
      ? goalsQuery.data
      : null;

  if (kpis.length === 0 && goals === null) return null;

  if (variant === "dashboard") {
    const kpiRows = sortKpis(kpis).map(kpiRow);
    const goalRows = goals ? goals.goals.map(goalRow) : [];
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
              <Row key={row.id} row={row} />
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
                <Row key={row.id} row={row} />
              ))}
            </div>
          </div>
        ) : null}
      </section>
    );
  }

  const model = buildKpiTopbarModel(kpis, goals);
  if (!model) return null;

  return <KpiTopbarPopover model={model} className={className} />;
}
