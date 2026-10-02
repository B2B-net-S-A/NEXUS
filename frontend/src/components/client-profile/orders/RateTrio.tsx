import type { ReactNode } from "react";

import { CALM_EMPTY, CALM_UNIT } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { splitRateLabel } from "./order-line-display";

/**
 * Stawka w jednej linii: kwota w równych cyfrach, jednostka drobnym drukiem.
 * Tekst zostaje ten sam co dotąd („1 000,00 zł/MD”); brak stawki to „—”.
 */
export function RateText({ label }: { label: string | null | undefined }) {
  if (!label || label === "—") return <span className={CALM_EMPTY}>—</span>;
  const parts = splitRateLabel(label);
  if (!parts) return <>{label}</>;
  return (
    <>
      {parts.amount} <span className={cn(CALM_UNIT, "ml-0")}>{parts.unit}</span>
    </>
  );
}

export interface RateTrioItem {
  label: string;
  value: ReactNode;
  /** Dopisek pod kwotą, np. „45% przychodu”. */
  note?: ReactNode;
}

/** Stawki obok siebie (Koszt / Przychód / Marża) — w panelach zamówień. */
export function RateTrio({ items, className }: { items: RateTrioItem[]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-3 gap-2", className)}>
      {items.map((item) => (
        <div key={item.label} className="min-w-0 rounded-md bg-muted/50 px-2.5 py-2">
          <dt className="text-[11px] leading-4 text-muted-foreground">{item.label}</dt>
          <dd className="min-w-0 break-words text-[13px] font-semibold leading-5 tabular-nums text-foreground">
            {item.value}
          </dd>
          {item.note ? (
            <dd className="text-[11px] leading-4 text-muted-foreground">{item.note}</dd>
          ) : null}
        </div>
      ))}
    </dl>
  );
}
