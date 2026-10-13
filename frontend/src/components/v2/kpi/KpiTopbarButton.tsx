"use client";

import { Check, ChevronDown, Target } from "lucide-react";

import { cn } from "@/lib/utils";

import type { KpiMark, KpiSegment, KpiTopbarModel } from "./kpi-topbar-model";

export interface KpiTopbarButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  model: KpiTopbarModel;
  open: boolean;
}

/** Znaczek tylko przy wyjątku: kropka „poniżej tempa” i znaczek „zrobione”. */
export function KpiMarkIcon({ mark }: { mark: KpiMark }) {
  if (mark === "behind") {
    return <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />;
  }
  if (mark === "hit") {
    return (
      <span
        aria-hidden
        className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-success-muted text-success-muted-foreground"
      >
        <Check className="h-2.5 w-2.5" strokeWidth={3.5} />
      </span>
    );
  }
  return null;
}

export function kpiValueClass(mark: KpiMark): string {
  if (mark === "behind") return "text-warning-muted-foreground";
  if (mark === "missed") return "text-muted-foreground";
  return "text-foreground";
}

function Segment({ segment, first }: { segment: KpiSegment; first: boolean }) {
  return (
    <span
      data-kpi-segment={segment.id}
      className={cn(
        // `whitespace-nowrap`: najmniejsza szerokość przycisku to CAŁY segment.
        // Z zawijaniem tekst łamał się w dwa wiersze i wystawał z ukrytego wiersza.
        "relative hidden h-full grow flex-col justify-center gap-px overflow-hidden whitespace-nowrap px-3 lg:flex",
        // Kreska należy do segmentu: gdy segment nie mieści się i spada do
        // ukrytego wiersza, znika razem z nim.
        !first &&
          "before:absolute before:inset-y-[7px] before:left-0 before:w-px before:bg-border before:content-['']",
      )}
    >
      <span className="text-[11px] leading-[13px] text-muted-foreground">
        <span className="2xl:hidden">{segment.labelCompact}</span>
        <span className="hidden 2xl:inline">{segment.label}</span>
      </span>
      <span className="flex items-center gap-1.5 text-[13px] leading-4 tabular-nums">
        <KpiMarkIcon mark={segment.mark} />
        <span className={cn("font-semibold", kpiValueClass(segment.mark))}>{segment.value}</span>
        {segment.rest ? (
          <span className="text-muted-foreground">
            {/* Forma zwarta („tydz.”, „mies.”) poniżej 1536 px — okno laptopa. */}
            <span className="2xl:hidden">{segment.restCompact}</span>
            <span className="hidden 2xl:inline">{segment.rest}</span>
          </span>
        ) : null}
      </span>
    </span>
  );
}

/**
 * Licznik celów w górnym pasku: do trzech podpisanych segmentów.
 *
 * Pokazuje tyle CAŁYCH segmentów, ile się mieści — w kolejności ważności.
 * Przycisk zawija segmenty (`flex-wrap`) i ma wysokość jednego wiersza, więc
 * segment, który się nie mieści, spada do ukrytego wiersza, zamiast ucinać się
 * w połowie albo zgniatać wyszukiwarkę. Zmierzone 13.10.2026: okno 1280 px
 * z przypiętym menu mieści trzy segmenty przy krótkich okruszkach i jeden przy
 * długich. Poniżej 1024 px słowo „Cele”; forma zwarta („tydz.”, „mies.”) do
 * 1535 px, od 1536 pełna z podpisem „czyje”. Wszystko jest w DOM naraz —
 * wybiera CSS, a nazwa dla czytnika ekranu zawsze mówi o wszystkich celach.
 */
export function KpiTopbarButton({
  model,
  open,
  className,
  ref,
  ...props
}: KpiTopbarButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type="button"
      // Jedna nazwa niezależna od szerokości okna — to samo, co mówią segmenty.
      aria-label={model.spoken}
      className={cn(
        // `lg:pr-7`: miejsce na strzałkę, która stoi przy prawej krawędzi niezależnie
        // od liczby widocznych segmentów. Poniżej 1024 px bez niej — słowo „Cele”
        // ma zajmować tyle, co dawne „KPI” (wyszukiwarka na tablecie i tak jest wąska).
        "relative flex h-9 max-w-full flex-wrap content-start items-stretch overflow-hidden rounded-lg border text-left transition-colors lg:pr-7",
        open
          ? "border-primary bg-background ring-2 ring-primary/20"
          : "border-border bg-background/60 hover:bg-background",
        className,
      )}
      {...props}
    >
      <span className="flex h-full items-center gap-2 whitespace-nowrap px-3 text-xs font-medium text-foreground lg:hidden">
        <Target className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
        Cele
      </span>
      {model.lead ? (
        <span className="hidden h-full flex-col justify-center gap-px whitespace-nowrap bg-muted px-3 2xl:flex">
          <span className="text-[11px] font-semibold leading-[13px] text-foreground">
            {model.lead.title}
          </span>
          <span className="text-[11px] leading-4 text-muted-foreground">{model.lead.subtitle}</span>
        </span>
      ) : null}
      {model.segments.map((segment, index) => (
        <Segment key={segment.id} segment={segment} first={index === 0} />
      ))}
      {/* Strzałka mówi „tu jest więcej” — także wtedy, gdy część segmentów się nie zmieściła. */}
      <ChevronDown
        aria-hidden
        className={cn(
          "pointer-events-none absolute right-2 top-1/2 hidden h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground transition-transform lg:block",
          open && "rotate-180",
        )}
      />
    </button>
  );
}
