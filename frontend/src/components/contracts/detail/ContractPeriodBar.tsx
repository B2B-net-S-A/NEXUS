"use client";
// Okres umowy i bieżącego zamówienia jako dwa paski z kreską „dziś”
// (przebudowa 19.11.2026, wariant A). Umowa bezterminowa wygasa w prawo.
import { cn } from "@/lib/utils";
import { fmtDatePl, relativeDays } from "@/lib/contract-happening";

const ms = (iso: string) => Date.parse(`${iso.slice(0, 10)}T00:00:00Z`);

export interface ContractPeriodBarProps {
  startDate: string | null;
  endDate: string | null;
  orderStart: string | null;
  orderEnd: string | null;
  today: string;
}

export function ContractPeriodBar({ startDate, endDate, orderStart, orderEnd, today }: ContractPeriodBarProps) {
  if (!startDate) return null;
  const anchors = [startDate, today, orderEnd, endDate].filter((v): v is string => Boolean(v));
  const lo = ms(startDate);
  const last = Math.max(...anchors.map(ms));
  const hi = last + Math.max((last - lo) * 0.12, 86_400_000 * 20);
  const pct = (iso: string) => Math.min(100, Math.max(0, ((ms(iso) - lo) / (hi - lo)) * 100));
  const open = !endDate;
  const orderFrom = orderStart ?? startDate;
  const toOrderEnd = orderEnd ? Math.round((ms(orderEnd) - ms(today)) / 86_400_000) : null;

  return (
    <div className="space-y-2" data-testid="contract-period-bar">
      <div className="relative h-[52px]" aria-hidden>
        <div className="absolute inset-x-0 top-1 flex h-5 items-center">
          <span className="w-[92px] shrink-0 text-[11.5px] text-muted-foreground">Umowa</span>
          <div className="relative h-2.5 flex-1">
            <div
              className={cn("absolute inset-y-0 rounded-full bg-muted-foreground/25", open && "rounded-r-none")}
              style={{ left: 0, width: open ? "100%" : `${pct(endDate as string)}%` }}
            />
            {open ? <div className="absolute inset-y-0 right-0 w-16 bg-gradient-to-r from-transparent to-card" /> : null}
          </div>
        </div>
        <div className="absolute inset-x-0 top-7 flex h-5 items-center">
          <span className="w-[92px] shrink-0 text-[11.5px] text-muted-foreground">Zamówienie</span>
          <div className="relative h-2.5 flex-1">
            {orderEnd ? (
              <div
                className="absolute inset-y-0 rounded-full bg-primary/45"
                style={{ left: `${pct(orderFrom)}%`, width: `${Math.max(pct(orderEnd) - pct(orderFrom), 1)}%` }}
              />
            ) : null}
          </div>
        </div>
        <div className="pointer-events-none absolute inset-y-0 left-[92px] right-0">
          <div className="absolute -top-0.5 bottom-0 w-px bg-foreground/70" style={{ left: `${pct(today)}%` }}>
            <span className="absolute -top-3.5 -translate-x-1/2 whitespace-nowrap text-[10.5px] font-medium text-foreground">dziś</span>
          </div>
        </div>
      </div>
      <dl className="grid grid-cols-3 gap-3 border-t border-border/60 pt-2 text-[12.5px]">
        <div>
          <dt className="text-muted-foreground">Umowa</dt>
          <dd className="font-medium tabular-nums text-foreground">
            od {fmtDatePl(startDate)} · {open ? "bezterminowa" : `do ${fmtDatePl(endDate as string)}`}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Bieżące zamówienie</dt>
          <dd className="font-medium tabular-nums text-foreground">
            {orderEnd ? `${fmtDatePl(orderFrom)} – ${fmtDatePl(orderEnd)}` : "brak"}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Do końca zamówienia</dt>
          <dd className="font-medium text-foreground">{toOrderEnd != null ? relativeDays(toOrderEnd) : "—"}</dd>
        </div>
      </dl>
    </div>
  );
}
