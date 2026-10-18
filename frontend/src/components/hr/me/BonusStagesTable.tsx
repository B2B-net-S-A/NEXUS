"use client";

import { Fragment } from "react";

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

import type { BonusStage, MyBonusItem } from "./overview-format";

const STAGE_CLASS: Record<BonusStage["state"], string> = {
  done: "text-muted-foreground",
  current: "font-medium text-foreground",
  todo: "text-muted-foreground/70",
};

/** Etapy premii w jednej linii: „umowa › 14 z 21 dni › decyzja Płac › wypłata”. */
export function BonusStages({ stages }: { stages: readonly BonusStage[] }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1 text-xs">
      {stages.map((stage, index) => (
        <Fragment key={`${stage.label}-${index}`}>
          {index > 0 ? (
            <span aria-hidden className="text-muted-foreground/60">
              ›
            </span>
          ) : null}
          <span
            className={STAGE_CLASS[stage.state]}
            aria-current={stage.state === "current" ? "step" : undefined}
          >
            {stage.label}
          </span>
        </Fragment>
      ))}
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
              <TableCell className="max-w-[280px]">
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
              <TableCell className="min-w-[220px]">
                <BonusStages stages={item.stages} />
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
