"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

import { KpiProgressBar } from "./KpiProgressBar";
import { KpiMarkIcon, kpiValueClass } from "./KpiTopbarButton";
import type { KpiPanelRow, KpiTopbarModel } from "./kpi-topbar-model";

export interface KpiGoalsPanelProps {
  model: KpiTopbarModel;
  /** Klik w link zamyka panel — Popover sam tego nie robi. */
  onNavigate?: () => void;
}

function statusClass(row: KpiPanelRow): string {
  if (row.state === "behind") return "text-warning-muted-foreground";
  if (row.state === "hit") return "text-success-muted-foreground";
  return "text-foreground";
}

/** Wiersz celu — także w Insights → „Mój miesiąc”. */
export function PanelRow({ row, onNavigate }: { row: KpiPanelRow; onNavigate?: () => void }) {
  return (
    <div className="flex flex-col gap-1.5" data-kpi-row={row.id}>
      <div className="flex items-center justify-between gap-2 text-[13px] leading-[18px]">
        <span className="font-medium text-foreground">{row.title}</span>
        <span className="flex items-center gap-1.5 tabular-nums">
          {row.mark === "hit" ? <KpiMarkIcon mark="hit" /> : null}
          <span className={cn("font-semibold", kpiValueClass(row.mark))}>{row.value}</span>
          {row.rest ? <span className="text-muted-foreground">{row.rest}</span> : null}
        </span>
      </div>
      {/* Bez paska, gdy nie ma czego mierzyć — pusty pasek czytałby się jak zero. */}
      {row.progressPct !== null ? (
        <KpiProgressBar
          id={row.id}
          progressPct={row.progressPct}
          state={row.state ?? "on_track"}
          expectedPct={row.expectedPct}
          variant="compact"
        />
      ) : null}
      {row.status || row.description ? (
        <p className="text-xs leading-4 text-muted-foreground">
          {row.status ? (
            <span className={cn("font-medium", statusClass(row))}>{row.status}</span>
          ) : null}
          {row.status && row.description ? " " : null}
          {row.description}
        </p>
      ) : null}
      {row.link ? (
        <Link
          href={row.link.href}
          onClick={onNavigate}
          className="w-fit text-xs font-medium text-primary hover:underline"
        >
          {row.link.label} →
        </Link>
      ) : null}
    </div>
  );
}

/**
 * Treść panelu celów otwieranego z licznika w górnym pasku. Bez zapytań —
 * rysuje model, więc harness `/preview/kpi-topbar` pokazuje go z propsów.
 */
export function KpiGoalsPanel({ model, onNavigate }: KpiGoalsPanelProps) {
  return (
    <div className="flex max-h-[min(560px,calc(100dvh-6rem))] flex-col text-foreground">
      <header className="flex items-baseline justify-between gap-3 px-4 pb-2.5 pt-3.5">
        <h2 className="text-sm font-semibold">{model.panelTitle}</h2>
        {model.panelAside ? (
          <span className="text-xs text-muted-foreground">{model.panelAside}</span>
        ) : null}
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {model.groups.map((group) => (
          <section key={group.id} aria-label={group.heading}>
            <div className="flex items-baseline justify-between gap-3 border-y border-border bg-muted/50 px-4 py-1.5">
              {/* Rozmiar na samym nagłówku — globalny styl `h3` nie dziedziczy go z rodzica. */}
              <h3 className="text-xs font-semibold">{group.heading}</h3>
              {group.aside ? (
                <span className="text-xs text-muted-foreground">{group.aside}</span>
              ) : null}
            </div>
            <div className="flex flex-col gap-3.5 px-4 py-3">
              {group.rows.map((row) => (
                <PanelRow key={row.id} row={row} onNavigate={onNavigate} />
              ))}
            </div>
          </section>
        ))}
        {model.facts.length > 0 ? (
          <dl className="flex flex-col gap-1 border-t border-border bg-muted/50 px-4 py-2.5 text-xs leading-[18px]">
            {model.facts.map((fact) => (
              <div key={fact.label} className="flex justify-between gap-3">
                <dt className="text-muted-foreground">{fact.label}</dt>
                <dd className="font-semibold tabular-nums">{fact.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
      {model.footnote || model.link ? (
        <footer className="flex items-center justify-between gap-3 border-t border-border px-4 pb-3 pt-2.5 text-xs leading-4">
          <span className="text-muted-foreground">{model.footnote}</span>
          {model.link ? (
            <Link
              href={model.link.href}
              onClick={onNavigate}
              className="shrink-0 whitespace-nowrap font-medium text-primary hover:underline"
            >
              {model.link.label} →
            </Link>
          ) : null}
        </footer>
      ) : null}
    </div>
  );
}
