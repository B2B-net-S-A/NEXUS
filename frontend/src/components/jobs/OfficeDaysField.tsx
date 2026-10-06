"use client";

import { Input } from "@/components/ui/input";
import { blurNumberInputOnWheel } from "@/lib/number-input";
import { cn } from "@/lib/utils";
import {
  MONTHLY_MAX,
  WEEKLY_MAX,
  type OfficeDaysPeriod,
} from "@/lib/office-days";

const PERIODS: { value: OfficeDaysPeriod; label: string; aria: string }[] = [
  { value: "week", label: "w tygodniu", aria: "Dni w tygodniu" },
  { value: "month", label: "w miesiącu", aria: "Dni w miesiącu" },
];

/**
 * Dni w biurze: liczba + „w tygodniu / w miesiącu” (0407). Miesięcznie tylko
 * przy pracy hybrydowej (`allowMonth`) — klient pisze „raz w miesiącu”.
 */
export function OfficeDaysField({
  id,
  value,
  period,
  onValueChange,
  onPeriodChange,
  disabled = false,
  allowMonth = true,
  inputClassName,
  placeholder,
  className,
}: {
  id?: string;
  value: string;
  period: OfficeDaysPeriod;
  onValueChange: (value: string) => void;
  onPeriodChange: (period: OfficeDaysPeriod) => void;
  disabled?: boolean;
  allowMonth?: boolean;
  inputClassName?: string;
  placeholder?: string;
  className?: string;
}) {
  const month = period === "month";
  return (
    // Zawija się: w wąskiej kolumnie (sekcja podstaw /jobs/new) przełącznik
    // schodzi pod liczbę zamiast wyjść poza kolumnę.
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
      <Input
        id={id}
        type="number"
        inputMode="numeric"
        onWheel={blurNumberInputOnWheel}
        min={month ? 1 : 0}
        max={month ? MONTHLY_MAX : WEEKLY_MAX}
        disabled={disabled}
        value={disabled ? "" : value}
        onChange={(e) => onValueChange(e.target.value)}
        placeholder={disabled ? "—" : (placeholder ?? (month ? "np. 1" : "np. 2"))}
        className={cn("w-20 shrink-0", inputClassName)}
      />
      <div
        role="radiogroup"
        aria-label="Jak często w biurze"
        className="flex min-h-9 items-center gap-0.5 rounded-lg bg-muted p-0.5"
      >
        {PERIODS.map((p) => {
          const active = period === p.value;
          const blocked = disabled || (p.value === "month" && !allowMonth);
          return (
            <button
              key={p.value}
              type="button"
              role="radio"
              aria-checked={active}
              aria-label={p.aria}
              disabled={blocked}
              title={
                p.value === "month" && !allowMonth && !disabled
                  ? "Dni w miesiącu tylko przy pracy hybrydowej"
                  : undefined
              }
              onClick={() => onPeriodChange(p.value)}
              className={cn(
                "min-h-8 whitespace-nowrap rounded-md px-2 text-xs leading-tight transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                active
                  ? "bg-card font-semibold text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {p.label}
            </button>
          );
        })}
      </div>
      {!disabled && (
        <p className="basis-full text-xs text-muted-foreground">
          Gdy klient podaje przedział (np. 4–6), wpisz górną liczbę.
        </p>
      )}
    </div>
  );
}
