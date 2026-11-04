"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { formatMoney } from "@/lib/money";

import type { MyBonusItem } from "./overview-format";

/**
 * Etap premii w jednej linii: bieżący krok, następny i pasek dni. Cała ścieżka
 * („podpis › kontrakt › … › wypłata”) to 7 słów w każdym wierszu, które zawijały
 * się i ucinały nazwiska, więc została w dymku i dla czytnika (zgłoszenie 03.11.2026).
 */
export function BonusStageNow({
  stages,
  progress,
}: Pick<MyBonusItem, "stages" | "progress">) {
  const index = stages.findIndex((stage) => stage.state === "current");
  // Premia rozliczona ma wszystkie etapy za sobą: bieżący jest ostatni.
  const current = stages[index === -1 ? stages.length - 1 : index];
  const next = index === -1 ? undefined : stages[index + 1];
  const path = stages.map((stage) => stage.label).join(" › ");
  return (
    <span className="block" title={path}>
      <span className="flex flex-wrap items-center gap-x-1.5 text-xs">
        <span className="font-medium text-foreground" aria-current="step">
          {current?.label}
        </span>
        {next ? <span className="text-muted-foreground">› {next.label}</span> : null}
      </span>
      <span className="sr-only">Cała ścieżka: {path}</span>
      {progress != null && progress < 100 ? (
        <span aria-hidden className="mt-1 block h-1 w-32 overflow-hidden rounded-full bg-muted">
          <span className="block h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
        </span>
      ) : null}
    </span>
  );
}

/** Kwota premii: szacunek z „~”, brak stawek — zdanie zamiast „0”. */
export function bonusAmountLabel(item: Pick<MyBonusItem, "amount" | "currency" | "estimate">): string {
  if (item.amount == null) return "po uzupełnieniu stawek";
  return `${item.estimate ? "~ " : ""}${formatMoney(item.amount, item.currency)}`;
}

/** „Premie i stawka”: za co, etap, kwota, kiedy — premie w drodze, przyznane i anulowane. */
export function BonusStagesTable({ items }: { items: readonly MyBonusItem[] }) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className="min-w-[680px]">
        <TableHeader>
          <TableRow>
            <TableHead className={CALM_HEAD}>Za co</TableHead>
            <TableHead className={CALM_HEAD}>Etap</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Kwota</TableHead>
            <TableHead className={CALM_HEAD}>Kiedy</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.key} className={CALM_ROW}>
              <TableCell className="max-w-[420px]">
                <span
                  className={cn(
                    "block truncate font-medium",
                    item.cancelled ? "text-muted-foreground line-through" : "text-foreground",
                  )}
                  title={item.title}
                >
                  {item.title}
                </span>
                <span className={CALM_SUBLINE}>{item.subtitle}</span>
              </TableCell>
              <TableCell className="min-w-[180px]">
                <BonusStageNow stages={item.stages} progress={item.progress} />
              </TableCell>
              <TableCell
                className={cn(
                  CALM_AMOUNT,
                  "whitespace-nowrap text-sm",
                  item.amount == null
                    ? "text-xs text-muted-foreground"
                    : item.cancelled
                      ? "text-muted-foreground"
                      : "font-medium text-foreground",
                )}
              >
                {bonusAmountLabel(item)}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{item.when}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
