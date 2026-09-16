"use client";

import type { OrderLineRead } from "@/lib/api/orderGroups";
import { lineScopeUsage } from "@/lib/order-line-usage";
import { cn } from "@/lib/utils";

import { formatMd } from "./MdBudgetBar";

/** Procent do paska i etykiety: zaokrąglony, bez ścinania powyżej 100 w
 *  tekście (przekroczenie jest faktem), ścięty do 100 tylko w szerokości. */
function pctOf(used: number, total: number): number | null {
  return total > 0 ? (used / total) * 100 : null;
}

function ScopeBar({
  label,
  used,
  total,
}: {
  label: string;
  used: number;
  total: number;
}) {
  const pct = pctOf(used, total);
  const exceeded = total > 0 && used > total;
  return (
    <div className="flex items-center gap-2">
      <span className="w-[4.5rem] shrink-0 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(100, pct ?? 0))}
        aria-label={`${label} — wykorzystano MD`}
        className="h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            exceeded ? "bg-destructive" : "bg-primary",
          )}
          style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%` }}
        />
      </div>
      <span
        className={cn(
          "shrink-0 text-xs tabular-nums",
          exceeded ? "font-semibold text-destructive" : "text-foreground",
        )}
      >
        <span className="font-semibold">{formatMd(used)}</span>
        <span className="text-muted-foreground"> / {formatMd(total)} MD</span>
        {pct !== null ? (
          <span className="text-muted-foreground"> {Math.round(pct)}%</span>
        ) : null}
      </span>
    </div>
  );
}

interface Props {
  line: OrderLineRead;
  className?: string;
}

/**
 * Dwa paski ZUŻYCIA (podstawa + opcja) i suma — Centrum e-Zdrowia.
 *
 * W odróżnieniu od `MdBudgetBar` wypełnienie odpowiada MD WYKORZYSTANYM, nie
 * pozostałym: etykieta obok czyta się „wykorzystano / limit", a umowa CeZ
 * rozlicza się z tego, ile zeszło z każdego zakresu. Dwa paski w konwencji
 * „pozostało" znaczyłyby dokładnie odwrotnie niż suma pod nimi.
 *
 * Brak opcji w umowie (`md_optional_total === null`) jest komunikatem, nie
 * pustym paskiem — pusty pasek „0 / 0" wyglądałby jak opcja do wykorzystania.
 */
export function MdScopeBars({ line, className }: Props) {
  const usage = lineScopeUsage(line);
  const totalExceeded = usage.totalBudget > 0 && usage.totalUsed > usage.totalBudget;
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <ScopeBar label="Podstawa" used={usage.baseUsed} total={usage.baseTotal} />
      {usage.optionalTotal === null ? (
        <p className="pl-[5rem] text-xs italic text-muted-foreground">
          brak opcji w umowie
        </p>
      ) : (
        <ScopeBar
          label="Opcja"
          used={usage.optionalUsed ?? 0}
          total={usage.optionalTotal}
        />
      )}
      <p
        className={cn(
          "text-xs tabular-nums",
          totalExceeded ? "font-semibold text-destructive" : "text-muted-foreground",
        )}
      >
        Wykorzystano łącznie{" "}
        <span className="font-semibold text-foreground">{formatMd(usage.totalUsed)}</span> /{" "}
        {formatMd(usage.totalBudget)} MD
        {usage.pct !== null ? ` ${Math.round(usage.pct)}%` : ""}
      </p>
    </div>
  );
}
