"use client";

import type { TrainingFees, TrainingRow } from "@/lib/api/trainings";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { compareFees, formatAmount } from "./training-model";

interface QuoteTableProps {
  fees: TrainingFees;
  /** Kwoty poprzedniego szkolenia tego trenera (z rejestru), gdy jest. */
  previousFees?: TrainingFees | null;
  previous?: Pick<TrainingRow, "title" | "session_date"> | null;
}

function Diff({ value }: { value: number | null }) {
  if (value === null || value === 0) return null;
  return (
    <span
      className={cn(
        "ml-1 text-xs",
        value > 0 ? "text-warning-muted-foreground" : "text-success-muted-foreground",
      )}
    >
      ({value > 0 ? "+" : "−"}
      {formatAmount(Math.abs(value))})
    </span>
  );
}

/** Wycena A–E (netto, zł) z kolumną poprzedniego szkolenia tego trenera. */
export function QuoteTable({ fees, previousFees = null, previous = null }: QuoteTableProps) {
  const comparison = compareFees(fees, previousFees);
  const withPrevious = previousFees !== null;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="sticky left-0 bg-card py-2 pr-3 font-medium">Pozycja</th>
            <th className="py-2 pr-3 text-right font-medium">Wycena</th>
            {withPrevious ? (
              <th className="py-2 text-right font-medium">
                Poprzednie szkolenie tego trenera
                {previous ? (
                  <span className="block font-normal">
                    {previous.title}
                    {previous.session_date ? ` · ${formatIsoDatePl(previous.session_date)}` : ""}
                  </span>
                ) : null}
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {comparison.rows.map((row) => (
            <tr key={row.key} className="border-b border-border/60">
              <td className="sticky left-0 bg-card py-2 pr-3">{row.label}</td>
              <td className="py-2 pr-3 text-right tabular-nums">
                {formatAmount(row.amount)}
                {withPrevious ? <Diff value={row.diff} /> : null}
              </td>
              {withPrevious ? (
                <td className="py-2 text-right tabular-nums text-muted-foreground">
                  {formatAmount(row.previous)}
                </td>
              ) : null}
            </tr>
          ))}
          <tr className="font-semibold">
            <td className="sticky left-0 bg-card py-2 pr-3">Razem netto</td>
            <td className="py-2 pr-3 text-right tabular-nums" data-testid="quote-total">
              {formatAmount(comparison.total)}
              {withPrevious ? <Diff value={comparison.totalDiff} /> : null}
            </td>
            {withPrevious ? (
              <td className="py-2 text-right tabular-nums text-muted-foreground">
                {formatAmount(comparison.previousTotal)}
              </td>
            ) : null}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
