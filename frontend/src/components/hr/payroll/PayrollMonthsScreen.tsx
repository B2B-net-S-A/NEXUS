"use client";

import Link from "next/link";

import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { HrConfig } from "@/lib/api/hr";
import { usePayrollMonths, type PayrollMonthSummary } from "@/lib/api/hr-payroll";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";
import { capitalize } from "@/lib/hr-employment-terms";

import { formatTotals, ymSegment } from "./payroll-format";

/** Stan miesiąca w liście (czysta funkcja — test bez renderu). */
export function monthState(row: PayrollMonthSummary): {
  label: string;
  tone: "success" | "warning" | "neutral";
} {
  if (row.status === "closed") return { label: "zamknięty", tone: "success" };
  if (row.can_close) return { label: "do zamknięcia", tone: "warning" };
  return { label: "w toku", tone: "neutral" };
}

/** „Ludzie → Płace”: ostatnie 13 miesięcy — stan, liczba osób, sumy per waluta. */
export function PayrollMonthsScreen({ config }: { config: HrConfig }) {
  const months = usePayrollMonths();
  const rows = months.data ?? [];
  const state = resolveViewState({
    isLoading: months.isLoading,
    isError: months.isError,
    error: months.error,
    isSuccess: months.isSuccess,
    isEmpty: rows.length === 0,
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Płace"
        description="Godziny z zaakceptowanych timesheetów × stawka, plus przyznane premie. Zamknięty miesiąc ma zamrożone kwoty."
        density="compact"
      />
      <PeopleSectionNav config={config} active="payroll" />
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie miesięcy…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={
            state === "forbidden"
              ? "Płace prowadzi dział Płac. Przełożony widzi godziny i premie zespołu w widoku miesiąca."
              : state === "not_found"
                ? "Moduł Płac nie jest jeszcze włączony."
                : undefined
          }
          onRetry={() => months.refetch()}
        />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Brak miesięcy do pokazania.
        </div>
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[680px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Miesiąc</TableHead>
                <TableHead className={CALM_HEAD}>Stan</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Osoby</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Razem</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Premie do decyzji</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => {
                const status = monthState(row);
                return (
                  <TableRow key={`${row.year}-${row.month}`} className={`${CALM_ROW} h-[46px]`}>
                    <TableCell>
                      <Link
                        href={`/people/payroll/${ymSegment(row.year, row.month)}`}
                        className="font-medium text-foreground hover:underline"
                      >
                        {capitalize(row.label)}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <StatusDot tone={status.tone}>{status.label}</StatusDot>
                    </TableCell>
                    <TableCell className={`${CALM_AMOUNT} text-sm`}>{row.people}</TableCell>
                    <TableCell className={`${CALM_AMOUNT} text-sm font-medium text-foreground`}>
                      {formatTotals(row.totals)}
                    </TableCell>
                    <TableCell className={`${CALM_AMOUNT} text-sm`}>
                      {row.pending_proposals > 0 ? (
                        row.pending_proposals
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
