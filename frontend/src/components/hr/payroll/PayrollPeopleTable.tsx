"use client";

import { useState, type ReactNode } from "react";
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
import { cn } from "@/lib/utils";

import {
  EMPLOYMENT_LABELS,
  formatHours,
  needsAttention,
  timesheetLabel,
  timesheetTone,
} from "./payroll-format";

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
  /** Akcja przy statusie timesheetu („Przypomnij”, „Ponagl przełożonego”). */
  renderTimesheetAction?: (person: PayrollPerson) => ReactNode;
}

type PeopleFilter = "all" | "attention";

/**
 * Osoby miesiąca płac: Płace widzą stawki i kwoty, przełożony godziny i premie
 * (D2). Wiersz „do wyjaśnienia” (raport bez akceptacji, godziny bez stawki)
 * jest podświetlony, a filtr pokazuje tylko takie.
 */
export function PayrollPeopleTable({ people, scope, renderTimesheetAction }: PayrollPeopleTableProps) {
  const payroll = scope === "payroll";
  const [filter, setFilter] = useState<PeopleFilter>("all");
  const attention = people.filter(needsAttention);
  const shown = filter === "attention" ? attention : people;
  const chip = (value: PeopleFilter, label: string) => (
    <button
      type="button"
      aria-pressed={filter === value}
      onClick={() => setFilter(value)}
      className={cn(
        "h-7 rounded-md border px-2.5 text-xs font-medium",
        filter === value
          ? "border-primary/40 bg-primary/10 text-primary"
          : "border-border bg-card text-foreground hover:bg-muted",
      )}
    >
      {label}
    </button>
  );
  return (
    <section aria-label="Osoby" className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
        <h2 className="text-sm font-semibold text-foreground">Osoby · {people.length}</h2>
        <div className="flex gap-1.5">
          {chip("all", "Wszyscy")}
          {chip("attention", `Do wyjaśnienia ${attention.length}`)}
        </div>
      </div>
      {shown.length === 0 ? (
        <p className="border-t border-border px-4 py-3 text-sm text-muted-foreground">
          Nic do wyjaśnienia — wszystkie raporty przyjęte, stawki są.
        </p>
      ) : (
        <div className="relative overflow-x-auto border-t border-border">
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
              {shown.map((person) => {
                const lines = person.lines ?? [];
                const flagged = needsAttention(person);
                const bonuses = payroll
                  ? lines.filter((l) => Number(l.bonus_total) > 0)
                  : (person.bonuses ?? []);
                return (
                  <TableRow key={person.user_id} className={cn(CALM_ROW, flagged && "bg-warning-muted/40")}>
                    <TableCell
                      className={cn(
                        "sticky left-0 bg-card",
                        // Ten sam odcień co wiersz, ale nieprzezroczysty (pod komórką przewija się tabela).
                        flagged &&
                          "bg-[linear-gradient(hsl(var(--warning-muted)/0.4),hsl(var(--warning-muted)/0.4))]",
                      )}
                    >
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
                      <TableCell className="text-sm">
                        {person.employment_type ? (
                          <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground">
                            {EMPLOYMENT_LABELS[person.employment_type] ?? person.employment_type}
                          </span>
                        ) : (
                          <span className={CALM_EMPTY}>—</span>
                        )}
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
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <StatusDot
                          tone={timesheetTone(person.timesheet_status, person.timesheet_required)}
                        >
                          {timesheetLabel(person.timesheet_status, person.timesheet_required)}
                        </StatusDot>
                        {renderTimesheetAction?.(person)}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
