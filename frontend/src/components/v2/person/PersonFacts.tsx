"use client";

/**
 * Fakty o osobie pod nazwiskiem — jeden wygląd w panelu osoby na Tablicy
 * i w przeglądzie Delivery Leada (jeden panel osoby, 04.10.2026). Teksty
 * liczy `lib/person-facts.ts`. Brak danych to „—”, nie znikający wiersz:
 * pusty rząd czyta się jak „bez zastrzeżeń”.
 */

import type { ReactNode } from "react";

import { budgetCheck, rateText } from "@/lib/person-facts";
import type { RateUnit } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface PersonFactRow {
  label: string;
  /** `null` = brak danych („—”). */
  value: ReactNode | null;
  /** Skąd wartość (np. „z karty”) — mały tekst pod nią. */
  hint?: string | null;
}

export function PersonFacts({
  rows,
  testId,
  title = "Warunki wobec rekrutacji",
}: {
  rows: ReadonlyArray<PersonFactRow>;
  testId?: string;
  title?: string;
}) {
  return (
    <div className="space-y-1 rounded-md border border-border bg-muted/30 px-2.5 py-2" data-testid={testId}>
      <div className="text-xs font-semibold text-foreground">{title}</div>
      <div className="grid grid-cols-[108px_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
        {rows.map((row) => (
          // `contents`: etykieta, wartość i dopisek są w siatce, a jeden rodzic
          // trzyma całą trójkę razem (czytnik ekranu, testy).
          <div key={row.label} className="contents">
            <span className="text-muted-foreground">{row.label}</span>
            <span className="min-w-0 text-foreground">
              {row.value ?? <span className="text-muted-foreground">—</span>}
            </span>
            {row.hint ? (
              <span className="col-start-2 -mt-1 text-[11px] text-muted-foreground">{row.hint}</span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Stawka kandydata w tej rekrutacji z oceną wobec budżetu zapisanego przy
 * ruchu na „Zweryfikowany”. Bez stawki — „brak stawki”.
 */
export function RateWithBudget({
  value,
  unit,
  currency,
  budgetMonthly,
}: {
  value: number | string | null | undefined;
  unit: RateUnit | null | undefined;
  currency: string | null | undefined;
  budgetMonthly: number | null | undefined;
}) {
  const text = rateText(value, unit, currency);
  if (text == null) return <span className="text-muted-foreground">brak stawki</span>;
  const check = budgetCheck(value, unit, currency, budgetMonthly);
  return (
    <>
      <span
        className={cn(
          "font-medium tabular-nums",
          check.verdict === "over"
            ? "text-warning"
            : check.verdict === "within"
              ? "text-success"
              : "text-foreground",
        )}
        title={
          check.monthly != null
            ? `≈ ${check.monthly.toLocaleString("pl-PL")} PLN/mc (21 dni × 8 h)`
            : undefined
        }
      >
        {text}
      </span>
      {budgetMonthly != null && (
        <span className="ml-1 text-muted-foreground">
          {check.verdict === "over"
            ? "ponad budżet"
            : check.verdict === "within"
              ? `w budżecie do ${budgetMonthly.toLocaleString("pl-PL")} PLN/mc`
              : "nie do porównania z budżetem (jednostka lub waluta)"}
        </span>
      )}
    </>
  );
}
