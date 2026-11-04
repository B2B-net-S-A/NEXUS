"use client";

import { useMemo, useState } from "react";

import type { EmploymentType } from "@/lib/api/hr";
import type { MySettlement } from "@/lib/api/hr-payroll";
import { capitalize, employmentTerms } from "@/lib/hr-employment-terms";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import type { ViewState } from "@/lib/view-state";

import { formatHours } from "../payroll/payroll-format";
import { BonusStagesTable } from "./BonusStagesTable";
import {
  ALL_MONTHS,
  bonusMonths,
  defaultMonth,
  monthAssigned,
  monthBase,
  monthKey,
  monthTotal,
  type BonusMonth,
} from "./bonus-months";
import { inTransitLabel, inTransitSummary, totalsLabel, type MyBonusItem } from "./overview-format";

const EMPTY_VALUE = "—";

/** Kwota otwartego miesiąca to szacunek: zmienia się do zamknięcia w Płacach. */
function estimated(month: BonusMonth, totals: Record<string, number | string>): string {
  if (Object.keys(totals).length === 0) return EMPTY_VALUE;
  const prefix = month.settled?.final ? "" : "~ ";
  return Object.entries(totals)
    .map(([currency, total]) => `${prefix}${formatMoney(total, currency)}`)
    .join(" · ");
}

/** Skąd podstawa: „160 h × 90,00 zł” albo powód, dla którego jej nie ma. */
function baseCaption(month: BonusMonth, state: ViewState, today: string): string {
  if (state === "loading") return "liczę…";
  if (state !== "ready" && state !== "empty") return "nie udało się policzyć";
  const { settled } = month;
  if (settled?.rate_missing) return "stawka nie ustawiona";
  const rate = settled?.lines.find((line) => line.hourly_rate != null);
  if (settled && rate && Object.keys(monthBase(month)).length > 0) {
    return `${formatHours(settled.hours)} h × ${formatMoney(rate.hourly_rate as string, rate.currency)}`;
  }
  // Zakładka pyta o rozliczenie tego roku, więc starszy miesiąc nie ma tu podstawy.
  return month.key < today.slice(0, 7) && !settled ? "bez danych o podstawie" : "jeszcze bez godzin";
}

function MonthSummary({
  month,
  state,
  today,
  form,
}: {
  month: BonusMonth;
  state: ViewState;
  today: string;
  form: EmploymentType | null | undefined;
}) {
  const words = employmentTerms(form);
  const transit = inTransitSummary(month.rows);
  const baseKnown = state === "ready" || state === "empty";
  const cell = "flex min-w-0 flex-col-reverse";
  const caption = "text-[11px] leading-4 text-muted-foreground";
  const value = "font-display text-base font-semibold leading-5 tabular-nums text-foreground";
  const assigned = monthAssigned(month);
  return (
    <section
      aria-label={`Podsumowanie: ${month.name} ${month.year}`}
      className="rounded-lg border border-border bg-card px-4 py-2.5"
    >
      <dl className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className={cell}>
          <dt className={caption}>Podstawa · {baseCaption(month, state, today)}</dt>
          <dd className={value}>{estimated(month, monthBase(month))}</dd>
        </div>
        <span aria-hidden className="text-muted-foreground">+</span>
        <div className={cell}>
          <dt className={caption}>{capitalize(words.bonuses)}</dt>
          <dd className={value}>{Object.keys(assigned).length > 0 ? totalsLabel(assigned) : EMPTY_VALUE}</dd>
        </div>
        <span aria-hidden className="text-muted-foreground">=</span>
        <div className={cell}>
          <dt className={caption}>Razem za {month.name}</dt>
          {/* Bez podstawy suma byłaby zaniżona, więc awaria rozliczenia to kreska, nie kwota. */}
          <dd className={cn(value, "text-primary")}>
            {baseKnown ? estimated(month, monthTotal(month)) : EMPTY_VALUE}
          </dd>
        </div>
        {transit.count > 0 ? (
          <div className={cn(cell, "ml-auto border-l border-border pl-4")}>
            <dt className={caption}>w drodze ({transit.count}) · poza sumą</dt>
            <dd className={cn(value, "text-muted-foreground")}>{inTransitLabel(transit)}</dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}

/** Kwota na przycisku miesiąca: przyznane, a gdy ich nie ma — szacunek „w drodze”. */
function chipAmount(month: BonusMonth): string {
  const assigned = monthAssigned(month);
  if (Object.keys(assigned).length > 0) return totalsLabel(assigned);
  const transit = inTransitSummary(month.rows);
  if (transit.count === 0) return EMPTY_VALUE;
  return Object.keys(transit.totals).length > 0 ? inTransitLabel(transit) : "w drodze";
}

function MonthPicker({
  months,
  selected,
  onSelect,
  today,
}: {
  months: readonly BonusMonth[];
  selected: string;
  onSelect: (key: string) => void;
  today: string;
}) {
  const currentKey = today.slice(0, 7);
  const currentYear = Number(today.slice(0, 4));
  const chip =
    "flex flex-auto flex-col items-center justify-center whitespace-nowrap rounded-md px-2 py-1 transition-colors pointer-coarse:min-h-10";
  const on = "bg-primary text-primary-foreground";
  const off = "text-foreground hover:bg-accent";
  return (
    <div
      role="group"
      aria-label="Miesiąc"
      data-tour="my-time.bonus-months"
      className="flex flex-wrap gap-0.5 rounded-lg border border-border bg-card p-0.5"
    >
      {months.map((month) => {
        const active = selected === month.key;
        const year = month.year === currentYear ? "" : ` ${month.year}`;
        return (
          <button
            key={month.key}
            type="button"
            aria-pressed={active}
            onClick={() => onSelect(month.key)}
            className={cn(chip, active ? on : off)}
          >
            <span className="text-xs font-medium">
              {month.name}
              {year}
              {month.key === currentKey ? " · teraz" : ""}
            </span>
            <span
              className={cn(
                "text-[11px] tabular-nums",
                active ? "text-primary-foreground/80" : "text-muted-foreground",
              )}
            >
              {chipAmount(month)}
            </span>
          </button>
        );
      })}
      <button
        type="button"
        aria-pressed={selected === ALL_MONTHS}
        onClick={() => onSelect(ALL_MONTHS)}
        className={cn(chip, "flex-none", selected === ALL_MONTHS ? on : off)}
      >
        <span className="text-xs font-medium">Wszystkie</span>
      </button>
    </div>
  );
}

interface BonusMonthsProps {
  items: readonly MyBonusItem[];
  /** Rozliczenie miesięcy; bez niego (ładuje się, awaria) lista i tak działa. */
  settlement: Pick<MySettlement, "months"> | undefined;
  settlementState: ViewState;
  today: string;
  form: EmploymentType | null | undefined;
}

/**
 * Premie po miesiącach (zgłoszenie 03.11.2026, makieta wariant A): rząd miesięcy,
 * „podstawa + premie = razem” i lista wybranego miesiąca. „Wszystkie” przywraca
 * pełną listę. Wybór tylko w stanie ekranu: bez niego liczy się domyślny miesiąc,
 * więc rozliczenie wczytane po chwili może go jeszcze poprawić.
 */
export function BonusMonths({ items, settlement, settlementState, today, form }: BonusMonthsProps) {
  const words = employmentTerms(form);
  const months = useMemo(() => bonusMonths(items, settlement), [items, settlement]);
  const [picked, setPicked] = useState<string | null>(null);
  const current = monthKey(Number(today.slice(0, 4)), Number(today.slice(5, 7)));
  const selected = picked ?? defaultMonth(months, current);
  const month = months.find((candidate) => candidate.key === selected);
  const rows = selected === ALL_MONTHS ? items : (month?.rows ?? []);
  return (
    <div className="space-y-2">
      <MonthPicker months={months} selected={selected} onSelect={setPicked} today={today} />
      {month ? <MonthSummary month={month} state={settlementState} today={today} form={form} /> : null}
      {rows.length > 0 ? (
        <BonusStagesTable items={rows} />
      ) : (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          W tym miesiącu nie ma {words.bonuses_genitive}.
        </p>
      )}
    </div>
  );
}
