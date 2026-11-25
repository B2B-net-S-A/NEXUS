"use client";

import type React from "react";
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useSalesFormChecks } from "@/lib/api/client-invoicing";
import { formatDayMonthPl, monthTitlePl } from "@/lib/date-pl";
import { countPl } from "@/lib/plural-pl";

/** Kropka + zdanie, które się zawija (StatusDot jest na krótkie etykiety, bez zawijania). */
function Line({ tone, children }: { tone: "success" | "warning" | "danger"; children: React.ReactNode }) {
  const dot = { success: "bg-success", warning: "bg-warning", danger: "bg-destructive" }[tone];
  return (
    <span className="flex min-w-0 items-start gap-1.5 text-xs font-medium text-foreground">
      <span aria-hidden className={`mt-1.5 size-1.5 shrink-0 rounded-full ${dot}`} />
      <span className="min-w-0">{children}</span>
    </span>
  );
}

/**
 * Kontrola formalna faktur z KSeF wystawionych poza NEXUSEM (eBI24): data
 * sprzedaży a okres, kod osoby przy „Contractor” (reguła klienta), MD ponad dni
 * robocze, osoba bez kontraktu. Zwinięta do jednego wiersza; rozwinięta — lista
 * faktur z uwagami. Awaria zapytania nie wygląda jak „bez uwag”.
 */
export function FormChecksPanel({
  year,
  month,
  period,
}: {
  year: number;
  month: number;
  period: string;
}) {
  const [open, setOpen] = useState(false);
  const report = useSalesFormChecks(year, month);
  const rows = report.data?.invoices ?? [];

  if (report.isError) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-4 py-2 text-sm">
        <Line tone="danger">
          {apiErrorMessage(
            report.error,
            "Nie udało się sprawdzić faktur z KSeF.",
          )}
        </Line>
        <Button size="sm" variant="ghost" onClick={() => report.refetch()}>
          Spróbuj ponownie
        </Button>
      </div>
    );
  }
  if (!report.isSuccess) {
    return (
      <p className="px-1 text-xs text-muted-foreground">
        Sprawdzanie faktur spoza NEXUSA…
      </p>
    );
  }

  const title = rows.length
    ? `Kontrola faktur spoza NEXUSA: ${countPl(rows.length, "faktura", "faktury", "faktur")} z uwagami (z ${report.data.checked})`
    : `Kontrola faktur spoza NEXUSA: bez uwag (${countPl(report.data.checked, "faktura", "faktury", "faktur")} za ${monthTitlePl(period).toLowerCase()})`;

  return (
    <section
      className="rounded-lg border border-border bg-card"
      aria-label="Kontrola faktur spoza NEXUSA"
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        disabled={!rows.length}
      >
        {rows.length ? (
          open ? (
            <ChevronDown
              className="h-4 w-4 shrink-0 text-muted-foreground"
              aria-hidden
            />
          ) : (
            <ChevronRight
              className="h-4 w-4 shrink-0 text-muted-foreground"
              aria-hidden
            />
          )
        ) : null}
        <Line tone={rows.length ? "warning" : "success"}>{title}</Line>
      </button>
      {open && rows.length ? (
        <ul className="max-h-[50dvh] divide-y divide-border overflow-y-auto border-t border-border">
          {rows.map((row) => (
            <li
              key={row.invoice_id}
              className="grid gap-1 px-4 py-2 text-sm md:grid-cols-[14rem_minmax(0,1fr)]"
            >
              <div className="min-w-0">
                <span
                  className="block truncate font-medium text-foreground"
                  title={row.ksef_number}
                >
                  {row.invoice_number}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {row.client_name ?? "nabywca spoza kartoteki"} · sprzedaż{" "}
                  {formatDayMonthPl(row.sale_date)}
                </span>
              </div>
              <ul className="list-disc pl-5 text-muted-foreground">
                {row.problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
