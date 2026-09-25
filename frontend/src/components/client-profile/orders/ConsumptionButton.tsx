"use client";

import type { LineConsumptionFlag, OrderLineRead } from "@/lib/api/orderGroups";
import { cn } from "@/lib/utils";

import { formatMd } from "./MdBudgetBar";

/** „sie" z `YYYY-MM` — dzień 15, żeby strefa czasowa nie cofnęła miesiąca. */
export function shortMonthPl(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  return new Intl.DateTimeFormat("pl-PL", { month: "short" })
    .format(new Date(Number(match[1]), Number(match[2]) - 1, 15))
    .replace(".", "");
}

const FLAG_REASON: Record<LineConsumptionFlag, string> = {
  negative_balance: "saldo osoby jest ujemne",
  missing_previous_month: "brakuje zejścia za poprzedni miesiąc",
  import_to_verify: "wiersz importu tej osoby czeka na weryfikację",
};

export function consumptionWarnings(line: OrderLineRead): string[] {
  return (line.consumption_flags ?? []).map((flag) => FLAG_REASON[flag] ?? flag);
}

/** Mini-wykres słupkowy zejść z ostatnich miesięcy (bez osi — skala względna). */
function Sparkline({ values }: { values: number[] }) {
  if (values.length === 0) return null;
  const max = Math.max(...values.map((v) => Math.abs(v)), 1);
  const width = values.length * 4 - 1;
  return (
    <svg
      width={width}
      height={14}
      viewBox={`0 0 ${width} 14`}
      aria-hidden="true"
      className="shrink-0"
      data-testid="consumption-sparkline"
    >
      {values.map((value, index) => {
        const height = Math.max(1, Math.round((Math.abs(value) / max) * 14));
        return (
          <rect
            key={index}
            x={index * 4}
            y={14 - height}
            width={3}
            height={height}
            rx={0.5}
            className={cn(
              "fill-current",
              index === values.length - 1 ? "opacity-100" : "opacity-50",
            )}
          />
        );
      })}
    </svg>
  );
}

interface Props {
  line: OrderLineRead;
  onClick: () => void;
}

/**
 * „Zużycie MD" zamiast ikony kalendarza (ticket 7, 25.09.2026): kalendarz nie
 * sugerował, że pod nim jest podgląd i edycja zużycia miesięcznego. Przycisk
 * pokazuje mini-wykres i ostatnią wartość („Zużycie · sie 3,7"), a pomarańczową
 * kropką ostrzega, gdy saldo jest ujemne, brakuje zejścia za poprzedni miesiąc
 * albo wiersz importu tej osoby czeka „Do weryfikacji".
 */
export function ConsumptionButton({ line, onClick }: Props) {
  const recent = line.consumption_recent ?? [];
  const last = recent.length > 0 ? recent[recent.length - 1] : null;
  const warnings = consumptionWarnings(line);
  const warn = warnings.length > 0;
  const title = [
    "Zużycie miesięczne – podgląd i edycja",
    ...warnings.map((reason) => `Uwaga: ${reason}`),
  ].join("\n");
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={`Zużycie MD — ${line.consultant_name}${
        warn ? ` (uwaga: ${warnings.join(", ")})` : ""
      }`}
      className={cn(
        "relative inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-1 text-xs font-medium transition-colors pointer-coarse:py-2",
        warn
          ? "border-warning/60 bg-warning-muted text-warning-muted-foreground hover:bg-warning-muted/80"
          : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      <Sparkline values={recent.map((point) => point.md)} />
      <span>
        Zużycie
        {last ? (
          <>
            {" · "}
            {shortMonthPl(last.period_month)}{" "}
            <span className="tabular-nums text-foreground">{formatMd(last.md)}</span>
          </>
        ) : null}
      </span>
      {warn ? (
        <span
          className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-warning ring-2 ring-card"
          aria-hidden="true"
          data-testid="consumption-warning-dot"
        />
      ) : null}
    </button>
  );
}
