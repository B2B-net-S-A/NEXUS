"use client";

import type { ReactNode } from "react";

import { StatusDot } from "@/components/ds/StatusDot";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { BonusRow } from "@/lib/api/hr-payroll";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatMoney } from "@/lib/money";
import { formatIsoDatePl, monthYearPl } from "@/lib/date-pl";

import {
  BONUS_STATUS_TONE,
  bonusStateLabel,
  bonusTitle,
  cancelReasonLabel,
  progressPercent,
} from "./payroll-format";

interface BonusTableProps {
  rows: BonusRow[];
  /** Kolumna „Osoba” (Płace i przełożony; w „Moim czasie” zbędna). */
  showRecipient?: boolean;
  /** Pasek postępu do terminu (propozycje „liczy się”). */
  showProgress?: boolean;
  renderActions?: (row: BonusRow) => ReactNode;
  minWidth?: string;
}

/** Spokojna tabela premii: za co, osoba, miesiąc, kwota, stan, akcje. */
export function BonusTable({
  rows,
  showRecipient = true,
  showProgress = false,
  renderActions,
  minWidth = "min-w-[760px]",
}: BonusTableProps) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className={minWidth}>
        <TableHeader>
          <TableRow>
            <TableHead className={CALM_HEAD}>Za co</TableHead>
            {showRecipient ? <TableHead className={CALM_HEAD}>Osoba</TableHead> : null}
            <TableHead className={CALM_HEAD}>Miesiąc</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Kwota</TableHead>
            <TableHead className={CALM_HEAD}>Stan</TableHead>
            {renderActions ? (
              <TableHead className={CALM_HEAD}>
                <span className="sr-only">Akcje</span>
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const percent = progressPercent(
              row.business_days_elapsed,
              row.business_days_required,
            );
            return (
              <TableRow key={row.id} className={CALM_ROW}>
                <TableCell className="max-w-[320px]">
                  <span className="block truncate font-medium text-foreground" title={bonusTitle(row)}>
                    {bonusTitle(row)}
                  </span>
                  <span className={CALM_SUBLINE}>
                    {row.category_label}
                    {row.eligible_on ? ` · termin ${formatIsoDatePl(row.eligible_on)}` : ""}
                    {row.edited ? " · kwota poprawiona" : ""}
                    {row.contract_ended_early ? (
                      <span className="text-warning">
                        {" · kontrakt skończył się przed terminem — premia przepada"}
                      </span>
                    ) : null}
                  </span>
                </TableCell>
                {showRecipient ? (
                  <TableCell className="whitespace-nowrap text-sm text-foreground">
                    {row.recipient_name ?? "—"}
                  </TableCell>
                ) : null}
                <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                  {monthYearPl({ year: row.period_year, month: row.period_month })}
                </TableCell>
                <TableCell className={`${CALM_AMOUNT} text-sm font-medium text-foreground`}>
                  {formatMoney(row.amount, row.currency)}
                </TableCell>
                <TableCell className="min-w-[150px]">
                  {showProgress && row.business_days_required ? (
                    <div className="space-y-1">
                      <span className="text-[11px] text-muted-foreground">
                        {row.business_days_elapsed ?? 0} z {row.business_days_required} dni
                        roboczych
                      </span>
                      <div
                        className="h-1.5 w-28 overflow-hidden rounded-full bg-muted"
                        role="progressbar"
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={percent}
                      >
                        <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
                      </div>
                    </div>
                  ) : (
                    <StatusDot
                      tone={BONUS_STATUS_TONE[row.status]}
                      note={
                        row.status === "cancelled" && row.cancel_reason !== "manual"
                          ? (cancelReasonLabel(row.cancel_reason) ?? undefined)
                          : undefined
                      }
                    >
                      {bonusStateLabel(row)}
                    </StatusDot>
                  )}
                </TableCell>
                {renderActions ? (
                  <TableCell className="whitespace-nowrap text-right">{renderActions(row)}</TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
