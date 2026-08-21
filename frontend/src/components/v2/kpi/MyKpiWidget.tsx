"use client";

import { useState } from"react";
import { Target } from"lucide-react";
import { cn } from"@/lib/utils";
import { useMyKpis } from"@/hooks/useMyKpis";
import type { KpiResult } from"@/lib/api";
import { KpiProgressBar } from"./KpiProgressBar";

interface Props {
 /** compact (topbar, 1 linia ikon + popover na hover) vs dashboard (siatka). */
 variant?:"compact" |"dashboard";
 className?: string;
}

const PERIOD_ORDER: Record<string, number> = { day: 0, week: 1, month: 2 };

function sortKpis(kpis: readonly KpiResult[]): KpiResult[] {
 return [...kpis].sort((a, b) => {
 const po = (PERIOD_ORDER[a.period] ?? 9) - (PERIOD_ORDER[b.period] ?? 9);
 if (po !== 0) return po;
 return a.kpi_id.localeCompare(b.kpi_id);
 });
}

function shortLabel(k: KpiResult): string {
 return `${k.current}/${k.target}`;
}

function stateEmoji(state: KpiResult["state"]): string {
 switch (state) {
 case"hit":
 case"ahead":
 return"🎯";
 case"on_track":
 return"→";
 case"behind":
 return"↓";
 case"missed":
 return"×";
 }
}

/**
 *"Moje KPI" — widget w TopbarV2 (wariant compact).
 *
 * - Role nieoperacyjne dostają pustą listę z backendu → widget zwraca null.
 * - Compact: 3 progress bary w linii + mini-popover na hover.
 * - Dashboard: pełny grid z tytułami i labelami. UWAGA: ten wariant nie ma
 *   dziś ŻADNEGO wywołania w repo. Docstring wskazywał na `DashboardV2`, ale
 *   tamten plik nigdy tego widgetu nie importował (i został usunięty jako
 *   sierota 2026-08-20). Zanim go użyjesz, sprawdź, czy preset `RoleDashboard`
 *   nie pokazuje już tych samych liczb.
 */
export function MyKpiWidget({ variant ="compact", className }: Props) {
 const { data, isLoading, error } = useMyKpis();
 const [hovered, setHovered] = useState(false);

 if (isLoading || error) return null;
 if (!data || data.length === 0) return null;

 const sorted = sortKpis(data);

 if (variant === "dashboard") {
 return (
 <section
 className={cn("rounded-lg border border-border","bg-card p-4",
 className,
 )}
 aria-label="Moje KPI"
 >
 <header className="flex items-center gap-2 mb-3">
 <Target className="h-4 w-4 text-primary" />
 <h2 className="text-sm font-semibold text-foreground">
 Twoje KPI
 </h2>
 </header>
 <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
 {sorted.map((k) => (
 <KpiProgressBar
 key={k.kpi_id}
 id={k.kpi_id}
 title={k.title_pl}
 label={shortLabel(k)}
 progressPct={k.progress_pct}
 state={k.state}
 variant="full"
 />
 ))}
 </div>
 </section>
 );
 }

 // compact: 3 najważniejsze (day > week > month)
 const top = sorted.slice(0, 3);

 return (
 <div
 className={cn("relative", className)}
 onMouseEnter={() => setHovered(true)}
 onMouseLeave={() => setHovered(false)}
 >
 <button
 type="button"
 className={cn("flex items-center gap-2 h-9 px-3 rounded-lg","border border-border","bg-background/60 hover:bg-background","text-xs text-muted-foreground transition-colors",
 )}
 aria-label="Moje KPI"
 >
 <Target className="h-3.5 w-3.5 text-primary shrink-0" />
 <span className="hidden lg:flex items-center gap-2">
 {top.map((k) => (
 <span
 key={k.kpi_id}
 className="flex items-center gap-1 tabular-nums"
 title={k.title_pl}
 >
 <span className="shrink-0">{stateEmoji(k.state)}</span>
 <span className="font-medium text-foreground">
 {shortLabel(k)}
 </span>
 </span>
 ))}
 </span>
 <span className="lg:hidden font-medium text-foreground">
 KPI
 </span>
 </button>

 {hovered && (
 <div
 className={cn("absolute right-0 top-full mt-2 w-72 p-3 z-50","rounded-lg border border-border","bg-card shadow-smd",
 )}
 role="tooltip"
 >
 <div className="text-xs font-semibold text-foreground mb-2">
 Twoje KPI dziś / tydzień / miesiąc
 </div>
 <div className="flex flex-col gap-2.5">
 {sorted.map((k) => (
 <KpiProgressBar
 key={k.kpi_id}
 id={k.kpi_id}
 title={k.title_pl}
 label={shortLabel(k)}
 progressPct={k.progress_pct}
 state={k.state}
 variant="compact"
 />
 ))}
 </div>
 </div>
 )}
 </div>
 );
}
