"use client";

import { StatusDot } from "@/components/ds/StatusDot";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PayableRow } from "@/lib/api/hr-payments";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

import { accountLabel, amountToPay, documentLabel, periodLabel } from "./payments-format";

/**
 * „Dla Finansów”: zatwierdzone do zapłaty. B2B — brutto faktury i tytuł
 * z numerem KSeF; zlecenie i UoP — brutto z NEXUSA, na rękę liczy Symfonia.
 * Rachunek tylko jako 4 ostatnie cyfry ze źródłem.
 */
export function FinanceTable({ rows }: { rows: PayableRow[] }) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className="min-w-[960px]">
        <TableHeader>
          <TableRow>
            <TableHead className={CALM_HEAD}>Osoba</TableHead>
            <TableHead className={CALM_HEAD}>Dokument</TableHead>
            <TableHead className={`${CALM_HEAD} text-right`}>Do zapłaty</TableHead>
            <TableHead className={CALM_HEAD}>Rachunek</TableHead>
            <TableHead className={CALM_HEAD}>Tytuł przelewu</TableHead>
            <TableHead className={CALM_HEAD}>Termin</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const account = accountLabel(row);
            return (
              <TableRow key={row.settlement_id} className={CALM_ROW}>
                <TableCell>
                  <span className="font-medium text-foreground">{row.name}</span>
                  <span className={CALM_SUBLINE}>
                    {row.form_label} · {periodLabel(row.year, row.month)}
                  </span>
                </TableCell>
                <TableCell className="text-sm">
                  {documentLabel(row)}
                  {row.invoices.some((i) => i.ksef_number) ? (
                    <span className={CALM_SUBLINE}>z KSeF</span>
                  ) : null}
                </TableCell>
                <TableCell className={CALM_AMOUNT}>
                  {amountToPay(row)}
                  <span className={CALM_SUBLINE}>
                    z NEXUSA {formatMoney(row.expected_amount, row.currency)}{" "}
                    {row.amount_basis === "net" ? "netto" : "brutto"}
                  </span>
                </TableCell>
                <TableCell>
                  <StatusDot tone={account.tone}>{account.text}</StatusDot>
                </TableCell>
                <TableCell className="max-w-[260px] break-words text-xs text-muted-foreground">
                  {row.title}
                  {row.batch_key ? (
                    <span className={CALM_SUBLINE}>w paczce przelewów</span>
                  ) : null}
                </TableCell>
                <TableCell className="whitespace-nowrap text-sm">
                  <StatusDot tone={row.overdue ? "danger" : "neutral"}>
                    {formatIsoDatePl(row.due_on)}
                  </StatusDot>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
