"use client";
// Karta „Obowiązuje teraz” nad osią aneksów (wariant A, 19.11.2026): stan
// kontraktu po wszystkich zmianach jednym zdaniem i jedna akcja „Dodaj aneks”.
// Treść liczy `amendmentsNow` (czysta funkcja obok).
import { Fragment, type ReactNode } from "react";
import { CALM_HEAD } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import type { AmendmentsNow } from "./amendments-now";

const Sep = () => <span className="text-muted-foreground"> · </span>;

export function AmendmentsNowCard({ now, actions }: { now: AmendmentsNow | null; actions?: ReactNode }) {
  // Bez danych kontraktu (harness, starszy wołający) zostaje sama akcja.
  if (!now) return actions ? <div className="flex justify-end">{actions}</div> : null;
  const hasLine = now.rates.length > 0 || now.order != null;
  return (
    <section aria-label="Obowiązuje teraz" className="rounded-xl border border-border bg-card px-4 py-3 shadow-xs">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 space-y-1">
          <h2 className={CALM_HEAD}>Obowiązuje teraz</h2>
          {hasLine ? (
            <p className="text-[14.5px] leading-6 text-foreground">
              {now.since ? <span className="text-muted-foreground">Od {formatIsoDatePl(now.since)}: </span> : null}
              {now.rates.map((rate, index) => (
                <Fragment key={rate.who}>
                  {index > 0 ? <Sep /> : null}
                  {rate.who}{" "}
                  <span className={cn("font-semibold tabular-nums", !rate.amount && "text-muted-foreground/60")}>
                    {rate.amount ?? "—"}
                  </span>
                  {rate.since ? <span className="text-muted-foreground"> od {formatIsoDatePl(rate.since)}</span> : null}
                </Fragment>
              ))}
              {now.order ? (
                <>
                  {now.rates.length > 0 ? <Sep /> : null}
                  zamówienie do <span className="font-semibold tabular-nums">{formatIsoDatePl(now.order.end)}</span>
                  {now.order.ended ? <span className="text-muted-foreground"> (zakończone)</span> : null}
                </>
              ) : null}
            </p>
          ) : null}
          {now.facts.length > 0 ? (
            <p className={hasLine ? "text-[12.5px] text-muted-foreground" : "text-[14.5px] leading-6 text-foreground"}>
              {now.facts.join(" · ")}
            </p>
          ) : null}
        </div>
        {actions ? <div className="shrink-0">{actions}</div> : null}
      </div>
    </section>
  );
}
