"use client";

import { AlertCircle, ArrowUp, ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

import type { LeagueMedal, LeagueMedalTone, LeagueTopbarModel } from "./league-topbar-model";

const MEDAL_CLASS: Record<LeagueMedalTone, string> = {
  gold: "bg-medal-gold text-medal-gold-foreground",
  silver: "bg-medal-silver text-medal-silver-foreground",
  bronze: "bg-medal-bronze text-medal-bronze-foreground",
  neutral: "bg-primary/10 text-primary",
  warn: "bg-warning-muted text-warning-muted-foreground",
  off: "bg-muted text-muted-foreground",
  error: "bg-destructive-muted text-destructive-muted-foreground",
};

/** Kółko z numerem miejsca (złote, srebrne, brązowe dla 1–3). Bez emoji. */
export function LeagueMedalBadge({ medal, size = "sm" }: { medal: LeagueMedal; size?: "sm" | "lg" }) {
  return (
    <span
      aria-hidden
      data-medal={medal.tone}
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-bold tabular-nums leading-none",
        size === "sm" ? "h-6 w-6 text-xs" : "h-[34px] w-[34px] text-base",
        MEDAL_CLASS[medal.tone],
      )}
    >
      {medal.text ?? <AlertCircle className={size === "sm" ? "h-3.5 w-3.5" : "h-[18px] w-[18px]"} />}
    </span>
  );
}

export interface LeagueTopbarButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  model: LeagueTopbarModel;
  open: boolean;
}

/**
 * Przycisk Ligi Mistrzów w górnym pasku — stoi przed licznikiem celów i nigdy
 * się nie ściska (grupa akcji daje mu `shrink-0`). Poniżej 1024 px samo kółko
 * z numerem, od 1024 px kółko i dwie linie: liga ze stanem nad samym wynikiem
 * („Liga · Q4” nad „385 pkt”). Jedna forma na każdą szerokość: zmierzone
 * 13.10.2026, dopiski w dolnej linii zabierały okruszkom do 105 px przy 1280 px,
 * a forma pełna od 1536 px (222–238 px) spychała cele do jednego segmentu.
 * Dystans jest w panelu i w nazwie dla czytnika ekranu.
 */
export function LeagueTopbarButton({
  model,
  open,
  className,
  ref,
  ...props
}: LeagueTopbarButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={model.spoken}
      data-league-button=""
      className={cn(
        "relative flex h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-lg border px-1.5 text-left transition-colors lg:pr-7",
        open
          ? "border-primary bg-background ring-2 ring-primary/20"
          : "border-border bg-background/60 hover:bg-background",
        className,
      )}
      {...props}
    >
      <LeagueMedalBadge medal={model.medal} />
      <span className="hidden flex-col justify-center gap-px lg:flex">
        <span className="text-[11px] leading-[13px] text-muted-foreground">{model.label}</span>
        <span className="flex items-center gap-1.5 text-[13px] leading-4 tabular-nums">
          <span className="font-semibold text-foreground">{model.value}</span>
          {model.up ? (
            <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold text-success-muted-foreground">
              <ArrowUp aria-hidden className="h-3 w-3" strokeWidth={3} />
              {model.up}
            </span>
          ) : null}
        </span>
      </span>
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
