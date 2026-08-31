"use client";

import { cn } from "@/lib/utils";

interface Props {
  /** MD pozostałe. Może być ujemne — przekroczony budżet jest faktem. */
  remaining: number | null;
  total: number | null;
  className?: string;
}

/** Sformatowana liczba MD — do 3 miejsc po przecinku, bez zer na końcu. */
export function formatMd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pl-PL", {
    maximumFractionDigits: 3,
    useGrouping: false,
  }).format(value);
}

/**
 * Pasek „Zużycie MD" — wypełnienie odpowiada MD POZOSTAŁYM, nie zużytym
 * (etykieta obok czyta się „pozostało / całość", więc pasek musi opadać razem
 * z liczbą po lewej; rosnący pasek przy malejącej liczbie czytałby się odwrotnie
 * do tego, co pokazuje).
 *
 * Wyczerpany budżet zmienia kolor na ostrzegawczy i NIE jest ścinany do zera —
 * przekroczenie jest informacją handlową, a nie stanem do ukrycia.
 */
export function MdBudgetBar({ remaining, total, className }: Props) {
  const hasBudget = total !== null && total > 0;
  const safeRemaining = remaining ?? 0;
  const pct = hasBudget
    ? Math.max(0, Math.min(100, (safeRemaining / (total as number)) * 100))
    : 0;
  const depleted = hasBudget && safeRemaining <= 0;
  const low = hasBudget && !depleted && pct <= 15;

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div
        className="h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Pozostałe MD"
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            depleted
              ? "bg-destructive"
              : low
                ? "bg-amber-500"
                : "bg-primary",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span
        className={cn(
          "shrink-0 text-sm tabular-nums",
          depleted ? "font-semibold text-destructive" : "text-foreground",
        )}
      >
        <span className="font-semibold">{formatMd(remaining)}</span>
        <span className="text-muted-foreground"> / {formatMd(total)} MD</span>
      </span>
    </div>
  );
}
