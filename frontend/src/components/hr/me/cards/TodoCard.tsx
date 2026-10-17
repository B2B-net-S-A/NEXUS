"use client";

import Link from "next/link";

import { useMyEquipment } from "@/lib/api/equipment";
import type { HrConfig, PersonFull } from "@/lib/api/hr";
import { useMyLifecycleTasks } from "@/lib/api/hr-lifecycle";
import { useMyMonth, useMyTimesheetHistory } from "@/lib/api/hr-time";
import type { YearMonth } from "@/lib/date-pl";
import { cn } from "@/lib/utils";

import { currentYearMonth } from "../../time/time-format";
import { todoItems } from "../overview-format";
import { Loading, OverviewCard, PartError, stateOf } from "./OverviewCard";

export function TodoCard({
  config,
  person,
  onOpenTab,
}: {
  config: HrConfig;
  person: PersonFull;
  onOpenTab: (value: string, month?: YearMonth) => void;
}) {
  const open = config.open_modules;
  const current = currentYearMonth();
  const tasks = useMyLifecycleTasks(open.lifecycle);
  const equipment = useMyEquipment(open.equipment);
  const month = useMyMonth(current.year, current.month, open.time);
  const history = useMyTimesheetHistory(open.time);
  const withTimesheets = open.time && person.timesheet_required;

  const items = todoItems({
    current,
    employmentType: person.employment_type,
    tasks: open.lifecycle ? (tasks.data ?? []) : null,
    protocols: open.equipment ? (equipment.data?.protocols ?? []) : null,
    timesheets: withTimesheets ? { history: history.data ?? [], month: month.data } : null,
  });
  const failures: { label: string; retry: () => void }[] = [];
  if (open.lifecycle && tasks.isError) {
    failures.push({ label: "zadań wejścia i odejścia", retry: () => tasks.refetch() });
  }
  if (open.equipment && equipment.isError && stateOf(equipment) === "error") {
    failures.push({ label: "protokołów sprzętu", retry: () => equipment.refetch() });
  }
  if (withTimesheets && (month.isError || history.isError)) {
    failures.push({
      label: "timesheetów",
      retry: () => {
        void month.refetch();
        void history.refetch();
      },
    });
  }

  const loading =
    (open.lifecycle && tasks.isLoading) ||
    (open.equipment && equipment.isLoading) ||
    (withTimesheets && (month.isLoading || history.isLoading));

  return (
    <OverviewCard title="Do zrobienia">
      {items.length > 0 ? (
        <ul className="space-y-1.5">
          {items.map((item) => (
            <li key={item.key} className="text-sm">
              {item.href ? (
                <Link href={item.href} className="font-medium text-foreground hover:underline">
                  {item.title}
                </Link>
              ) : item.tab ? (
                <button
                  type="button"
                  onClick={() => item.tab && onOpenTab(item.tab, item.month)}
                  className="text-left font-medium text-foreground hover:underline"
                >
                  {item.title}
                </button>
              ) : (
                <span className="font-medium text-foreground">{item.title}</span>
              )}
              {item.detail ? (
                <span className={cn("block text-xs", item.overdue ? "text-destructive" : "text-muted-foreground")}>
                  {item.detail}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : loading ? (
        <Loading />
      ) : failures.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nic do zrobienia.</p>
      ) : null}
      {failures.map((failure) => (
        <PartError
          key={failure.label}
          label={`Nie udało się wczytać ${failure.label}.`}
          onRetry={failure.retry}
        />
      ))}
    </OverviewCard>
  );
}
