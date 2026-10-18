"use client";

import Link from "next/link";

import { StatusDot } from "@/components/ds/StatusDot";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { PayrollPerson } from "@/lib/api/hr-payroll";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatMoney } from "@/lib/money";

import { EMPLOYMENT_LABELS, formatHours, timesheetLabel, timesheetTone } from "./payroll-format";

function Stacked({ values }: { values: string[] }) {
  if (values.length === 0) return <span className={CALM_EMPTY}>—</span>;
  return (
    <>
      {values.map((value, index) => (
        <span key={index} className="block">
          {value}
        </span>
      ))}
    </>
  );
}

interface PayrollPeopleTableProps {
  people: PayrollPerson[];
  scope: "payroll" | "team";
}

/** Osoby miesiąca płac: Płace widzą stawki i kwoty, przełożony godziny i premie (D2). */
export function PayrollPeopleTable({ people, scope }: PayrollPeopleTableProps) {
  const payroll = scope === "payroll";
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className={payroll ? "min-w-[980px]" : "min-w-[620px]"}>
        <TableHeader>
          <TableRow>
            <TableHead className={`${CALM_HEAD} sticky left-0 bg-card`}>Osoba</TableHead>
            {payroll ? <TableHead className={CALM_HEAD}>Forma</TableHead> : null}
            <TableHead className={`${CALM_HEAD} text-right`}>Godziny</TableHead>
            {payroll ? (
              <>
                <TableHead className={`${CALM_HEAD} text-right`}>Stawka /h</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Za godziny</TableHead>
              </>
            ) : null}
            <TableHead className={`${CALM_HEAD} text-right`}>Premie</TableHead>
            {payroll ? <TableHead className={`${CALM_HEAD} text-right`}>Razem</TableHead> : null}
            <TableHead className={CALM_HEAD}>Timesheet</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {people.map((person) => {
            const lines = person.lines ?? [];
            const bonuses = payroll
              ? lines.filter((l) => Number(l.bonus_total) > 0)
              : (person.bonuses ?? []);
            return (
              <TableRow key={person.user_id} className={CALM_ROW}>
                <TableCell className="sticky left-0 bg-card">
                  <Link
                    href={`/people/${person.user_id}`}
                    className="font-medium text-foreground hover:underline"
                  >
                    {person.name}
                  </Link>
                  {person.rate_missing ? (
                    <span className={CALM_SUBLINE}>brak stawki — godziny bez kwoty</span>
                  ) : null}
                </TableCell>
                {payroll ? (
                  <TableCell className="text-sm text-muted-foreground">
                    {EMPLOYMENT_LABELS[person.employment_type ?? ""] ?? "—"}
                  </TableCell>
                ) : null}
                <TableCell className={`${CALM_AMOUNT} text-sm`}>
                  {Number(person.hours) > 0 ? formatHours(person.hours) : <span className={CALM_EMPTY}>—</span>}
                  {Number(person.overtime_hours) > 0 ? (
                    <span className={CALM_SUBLINE}>
                      w tym {formatHours(person.overtime_hours)} ponad normę
                    </span>
                  ) : null}
                </TableCell>
                {payroll ? (
                  <>
                    <TableCell className={`${CALM_AMOUNT} text-sm`}>
                      <Stacked
                        values={lines
                          .filter((l) => l.hourly_rate !== null)
                          .map((l) => formatMoney(l.hourly_rate, l.currency))}
                      />
                    </TableCell>
                    <TableCell className={`${CALM_AMOUNT} text-sm`}>
                      <Stacked
                        values={lines
                          .filter((l) => l.hours_amount !== null)
                          .map((l) => formatMoney(l.hours_amount, l.currency))}
                      />
                    </TableCell>
                  </>
                ) : null}
                <TableCell className={`${CALM_AMOUNT} text-sm`}>
                  <Stacked values={bonuses.map((b) => formatMoney(b.bonus_total, b.currency))} />
                </TableCell>
                {payroll ? (
                  <TableCell className={`${CALM_AMOUNT} text-sm font-semibold text-foreground`}>
                    <Stacked
                      values={lines
                        .filter((l) => Number(l.total) !== 0)
                        .map((l) => formatMoney(l.total, l.currency))}
                    />
                  </TableCell>
                ) : null}
                <TableCell>
                  <StatusDot
                    tone={timesheetTone(person.timesheet_status, person.timesheet_required)}
                  >
                    {timesheetLabel(person.timesheet_status, person.timesheet_required)}
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
