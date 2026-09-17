"use client";

import type { OrderLineRead } from "@/lib/api/orderGroups";
import { lineScopeRemaining, lineScopeUsage } from "@/lib/order-line-usage";
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

// ── Karta konsultanta CeZ: bloki PODSTAWA / OPCJA + pasek „Łącznie" ─────────

function barWidth(pct: number | null): string {
  return `${Math.max(0, Math.min(100, pct ?? 0))}%`;
}

/** „Pozostało N MD" albo — przy przekroczeniu — „Przekroczono o N MD". */
function RemainingText({ remaining, lowercase = false }: { remaining: number; lowercase?: boolean }) {
  if (remaining < 0) {
    return (
      <span className="font-semibold text-destructive">
        {lowercase ? "przekroczono" : "Przekroczono"} o {formatMd(-remaining)} MD
      </span>
    );
  }
  return (
    <span>
      {lowercase ? "pozostało" : "Pozostało"}{" "}
      <span className="font-semibold text-foreground">{formatMd(remaining)} MD</span>
    </span>
  );
}

function ScopePanel({
  label,
  used,
  total,
  pct,
  remaining,
  fillClassName,
}: {
  label: string;
  used: number;
  total: number;
  pct: number | null;
  remaining: number;
  fillClassName: string;
}) {
  const exceeded = remaining < 0;
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span
          className={cn(
            "text-xs font-semibold tabular-nums",
            exceeded ? "text-destructive" : "text-foreground",
          )}
        >
          {formatMd(used)} / {formatMd(total)} MD
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(100, pct ?? 0))}
        aria-label={`${label} — wykorzystano MD`}
        className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn("h-full rounded-full transition-all", exceeded ? "bg-destructive" : fillClassName)}
          style={{ width: barWidth(pct) }}
        />
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-2 text-[11px] tabular-nums text-muted-foreground">
        <span>{pct !== null ? `${Math.round(pct)}% wykorzystane` : "—"}</span>
        <RemainingText remaining={remaining} />
      </div>
    </div>
  );
}

/**
 * Dwie kolumny karty konsultanta CeZ: PODSTAWA i OPCJA, każda z paskiem
 * zużycia, „wykorzystano / limit" i jawnym „Pozostało N MD".
 *
 * Renderuje DWA elementy siatki (fragment), żeby rodzic ustawiał je w jednym
 * rzędzie ze stawką. Brak opcji w umowie zajmuje miejsce bloku wyciszonym
 * komunikatem — pusty pasek „0 / 0" wyglądałby jak opcja do wykorzystania.
 */
export function MdScopePanels({ line }: Props) {
  const usage = lineScopeUsage(line);
  const rest = lineScopeRemaining(line);
  return (
    <>
      <ScopePanel
        label="Podstawa"
        used={usage.baseUsed}
        total={usage.baseTotal}
        pct={rest.basePct}
        remaining={rest.baseRemaining}
        fillClassName="bg-primary"
      />
      {usage.optionalTotal === null || rest.optionalRemaining === null ? (
        <div className="flex min-h-[2.75rem] items-center justify-center text-xs italic text-muted-foreground">
          Brak opcji w umowie
        </div>
      ) : (
        <ScopePanel
          label="Opcja"
          used={usage.optionalUsed ?? 0}
          total={usage.optionalTotal}
          pct={rest.optionalPct}
          remaining={rest.optionalRemaining}
          fillClassName="bg-primary/60"
        />
      )}
    </>
  );
}

/**
 * Pasek „Łącznie" karty konsultanta CeZ — podstawa + opcja (albo sama
 * podstawa, gdy umowa opcji nie ma). „Pozostało" to serwerowe `md_remaining`,
 * więc przy korekcie ręcznej dopisujemy ją wprost: bez tego suma „pozostało"
 * z dwóch bloków wyżej nie zgadzałaby się z tą liczbą bez wyjaśnienia.
 */
export function MdScopeTotalBar({ line, className }: Props) {
  const usage = lineScopeUsage(line);
  const rest = lineScopeRemaining(line);
  const exceeded = rest.totalRemaining < 0;
  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-muted/60 px-3 py-1.5",
        className,
      )}
    >
      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Łącznie
      </span>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(100, usage.pct ?? 0))}
        aria-label="Łącznie — wykorzystano MD"
        className="h-1.5 min-w-[6rem] flex-1 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            exceeded ? "bg-destructive" : "bg-foreground",
          )}
          style={{ width: barWidth(usage.pct) }}
        />
      </div>
      <span
        className={cn(
          "text-xs font-semibold tabular-nums",
          exceeded ? "text-destructive" : "text-foreground",
        )}
      >
        {formatMd(usage.totalUsed)} / {formatMd(usage.totalBudget)} MD
        {usage.pct !== null ? ` (${Math.round(usage.pct)}%)` : ""}
      </span>
      <span className="text-xs tabular-nums text-muted-foreground">
        <RemainingText remaining={rest.totalRemaining} lowercase />
        {rest.adjustment !== 0 ? (
          <span>
            {" "}
            (w tym korekta {rest.adjustment > 0 ? "+" : "−"}
            {formatMd(Math.abs(rest.adjustment))} MD)
          </span>
        ) : null}
      </span>
    </div>
  );
}
