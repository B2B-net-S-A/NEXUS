"use client";

import Link from "next/link";

import { useMyEquipment } from "@/lib/api/equipment";
import type { HrConfig, OwnProfile } from "@/lib/api/hr";
import { useMyLifecycleTasks } from "@/lib/api/hr-lifecycle";
import { useMyMonth, useMyTimesheetHistory } from "@/lib/api/hr-time";
import type { YearMonth } from "@/lib/date-pl";
import { Button } from "@/components/ui/button";
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
  person: OwnProfile;
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
    <OverviewCard
      title="Do zrobienia"
      aside={items.length > 0 ? String(items.length) : undefined}
      className="gap-0"
    >
      {items.length > 0 ? (
        <ul className="mt-1">
          {items.map((item) => (
            <li
              key={item.key}
              className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-2.5 border-t border-border py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-foreground" title={item.title}>
                  {item.title}
                </p>
                {item.detail ? (
                  <p className="truncate text-xs text-muted-foreground">{item.detail}</p>
                ) : null}
              </div>
              {item.due ? (
                <span
                  className={cn(
                    "whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
                    item.overdue
                      ? "bg-destructive-muted text-destructive-muted-foreground"
                      : "bg-muted text-foreground",
                  )}
                >
                  {item.due}
                </span>
              ) : (
                <span aria-hidden />
              )}
              {item.action && item.href ? (
                <Button asChild size="sm" variant="outline" className="h-7 px-2.5">
                  <Link href={item.href} aria-label={item.title}>
                    {item.action}
                  </Link>
                </Button>
              ) : item.action && item.tab ? (
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 px-2.5"
                  aria-label={item.title}
                  onClick={() => item.tab && onOpenTab(item.tab, item.month)}
                >
                  {item.action}
                </Button>
              ) : (
                <span aria-hidden />
              )}
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
