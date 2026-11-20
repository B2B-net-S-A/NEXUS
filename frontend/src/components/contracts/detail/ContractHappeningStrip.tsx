"use client";
// Pas „Co się dzieje” pod nagłówkiem kontraktu (przebudowa 19.11.2026,
// wariant A). Treść liczy `lib/contract-happening.ts`; o tym, czy osoba może
// użyć akcji i co ona otwiera, decyduje strona (`renderAction`).
import type { ReactNode } from "react";
import { CalendarClock, CircleDollarSign, HeartPulse } from "lucide-react";
import { cn } from "@/lib/utils";
import type { HappeningActionId, HappeningItem, HappeningTone } from "@/lib/contract-happening";

const TONE_BAR: Record<HappeningTone, string> = {
  danger: "bg-destructive",
  warning: "bg-warning",
  info: "bg-info",
};
const TONE_ICON: Record<HappeningTone, string> = {
  danger: "text-destructive",
  warning: "text-warning",
  info: "text-info",
};
const ICON = { end: CalendarClock, order_end: CalendarClock, care: HeartPulse, rate: CircleDollarSign } as const;

export interface ContractHappeningStripProps {
  items: HappeningItem[];
  /** Przycisk albo link dla akcji; `null`, gdy osoba nie ma do niej prawa. */
  renderAction: (action: HappeningActionId, item: HappeningItem) => ReactNode | null;
}

export function ContractHappeningStrip({ items, renderAction }: ContractHappeningStripProps) {
  if (items.length === 0) return null;
  return (
    <section
      aria-label="Co się dzieje"
      className="overflow-hidden rounded-xl border border-border bg-card shadow-xs"
      data-testid="contract-happening"
    >
      <ul className="divide-y divide-border/70">
        {items.map((item) => {
          const Icon = ICON[item.id];
          const actions = item.actions.map((a) => ({ id: a, node: renderAction(a, item) })).filter((a) => a.node != null);
          return (
            <li key={item.id} className="relative flex flex-wrap items-center gap-x-3 gap-y-2 py-2.5 pl-4 pr-3" data-happening={item.id}>
              <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", TONE_BAR[item.tone])} />
              <Icon aria-hidden className={cn("size-4 shrink-0", TONE_ICON[item.tone])} />
              <div className="min-w-0 flex-1">
                <p className="text-[13.5px] font-semibold leading-5 text-foreground">{item.lead}</p>
                {item.detail ? <p className="text-[12.5px] leading-5 text-muted-foreground">{item.detail}</p> : null}
              </div>
              {actions.length > 0 ? (
                <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                  {actions.map((a) => (
                    <span key={a.id} className="contents">
                      {a.node}
                    </span>
                  ))}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
