"use client";

import { useEffect, useRef, useState } from"react";
import { cn } from"@/lib/utils";
import type { KpiState } from"@/lib/api";
import { useThemeStore } from"@/store/theme";
import { celebrate } from"@/lib/celebrate";

interface Props {
 /** Wartość 0-100+ (może przekroczyć 100 przy over-hit) */
 progressPct: number;
 state: KpiState;
 /** Sticky label (np."8/10") */
 label?: string;
 /** Krótki tytuł (np."Aktywności dziś") */
 title?: string;
 /** Kompaktowy variant (widget w topbarze) vs normalny (drawer/dashboard). */
 variant?:"compact" |"full";
 /** Stabilny identyfikator KPI — dedup „level up" celebrate (raz na sesję). */
 id?: string;
 className?: string;
}

// Each quest fires its "level up" celebration at most once per session, even if
// several KpiProgressBar instances render the same KPI.
const celebratedQuests = new Set<string>();

const STATE_BAR_CLASS: Record<KpiState, string> = {
 hit: "bg-emerald-500",
 ahead: "bg-emerald-500",
 on_track: "bg-primary",
 behind: "bg-amber-500",
 missed: "bg-neutral-400",
};

const STATE_TEXT_CLASS: Record<KpiState, string> = {
 hit: "text-emerald-700",
 ahead: "text-emerald-700",
 on_track: "text-primary",
 behind: "text-amber-700",
 missed: "text-neutral-500",
};

/**
 * Reusable progress bar dla widget'a KPI + drawera.
 * Kolor paska i tekstu zależy od state'u.
 */
export function KpiProgressBar({
 progressPct,
 state,
 label,
 title,
 variant ="full",
 id,
 className,
}: Props) {
 const kidsMode = useThemeStore((s) => s.kidsMode);
 const [flash, setFlash] = useState(false);
 const prevPct = useRef<number | null>(null);

 // Kids mode: when a quest crosses its target (→ ≥100%), flash + level-up
 // celebration (deduped per KPI per session). Inert outside game mode.
 useEffect(() => {
 const prev = prevPct.current;
 prevPct.current = progressPct;
 if (!kidsMode) return;
 if (prev != null && prev < 100 && progressPct >= 100) {
 setFlash(true);
 const t = window.setTimeout(() => setFlash(false), 900);
 if (id && !celebratedQuests.has(id)) {
 celebratedQuests.add(id);
 celebrate({ variant: "levelup", message: "Poziom zaliczony! 🏆" });
 }
 return () => window.clearTimeout(t);
 }
 }, [progressPct, kidsMode, id]);

 const clamped = Math.min(100, Math.max(0, progressPct));
 const trackClass =
 variant === "compact" ?"h-1.5" :"h-2";
 const rootPad =
 variant === "compact" ?"gap-0.5" :"gap-1";
 // Quest flair in Kids mode: ⭐ in progress, 🏆 once complete.
 const questIcon = progressPct >= 100 ?"🏆" :"⭐";

 return (
 <div className={cn("flex flex-col min-w-0", rootPad, className)}>
 {(title || label) && (
 <div className="flex items-center justify-between gap-2 text-xs">
 {title ? (
 <span className="truncate text-muted-foreground">
 {title}
 </span>
 ) : (
 <span />
 )}
 {label && (
 <span
 className={cn("font-medium tabular-nums shrink-0",
 STATE_TEXT_CLASS[state],
 )}
 >
 {kidsMode ? `${questIcon} ${label}` : label}
 </span>
 )}
 </div>
 )}
 <div
 className={cn("w-full rounded-full bg-background overflow-hidden",
 trackClass,
 flash &&"kids-levelup-flash",
 )}
 aria-valuenow={Math.round(progressPct)}
 aria-valuemin={0}
 aria-valuemax={100}
 role="progressbar"
 >
 <div
 className={cn("h-full rounded-full transition-all",
 STATE_BAR_CLASS[state],
 )}
 style={{ width: `${clamped}%` }}
 />
 </div>
 </div>
 );
}
