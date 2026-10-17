"use client"

// Kafelek „Sprzęt do zrobienia” (17.10.2026): otwarte zadania recepcji z tej
// samej listy co zakładka „Do zrobienia” (`/api/equipment/tasks?status=otwarte`,
// ten sam klucz zapytania). Terminy liczy serwer (zestaw kontraktora: 7 dni
// roboczych przed startem, ze świętami i dniami wolnymi firmy) — kafelek ich
// nie przelicza, tylko pokazuje najbliższe. Awaria = blok błędu, nie „0”.

import Link from "next/link"

import { dueLabel, TASK_KIND_LABELS } from "@/components/equipment/equipment-format"
import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { useEquipmentTasks, type EquipmentTask } from "@/lib/api/equipment"
import { countPl } from "@/lib/plural-pl"
import { cn } from "@/lib/utils"
import { resolveViewState } from "@/lib/view-state"

const PREVIEW = 4

/** Ile otwartych i ile po terminie (termin i spóźnienie liczy serwer). */
export function equipmentTaskStats(tasks: readonly EquipmentTask[]): {
  open: number
  overdue: number
} {
  return { open: tasks.length, overdue: tasks.filter((task) => task.overdue_days > 0).length }
}

export function EquipmentTasksTile() {
  const tasks = useEquipmentTasks("otwarte")
  const rows = tasks.data ?? []
  const state = resolveViewState({
    isLoading: tasks.isLoading,
    isError: tasks.isError,
    error: tasks.error,
    isSuccess: tasks.isSuccess,
    isEmpty: rows.length === 0,
  })
  if (state === "loading") return <Skeleton className="h-full min-h-[48px] w-full" />
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <WidgetErrorBlock error={tasks.error} onRetry={() => tasks.refetch()} />
  }

  const stats = equipmentTaskStats(rows)
  return (
    <div className="flex h-full flex-col gap-2 text-sm">
      {state === "empty" ? (
        <p className="text-muted-foreground">Nic do zrobienia przy sprzęcie.</p>
      ) : (
        <>
          <p className="text-foreground">
            {countPl(stats.open, "otwarte zadanie", "otwarte zadania", "otwartych zadań")}
            {stats.overdue > 0 ? (
              <span className="text-destructive"> · {stats.overdue} po terminie</span>
            ) : null}
          </p>
          <ul className="flex flex-col gap-1.5">
            {rows.slice(0, PREVIEW).map((task) => (
              <li
                key={task.id}
                className={cn(
                  "min-w-0 rounded-md border-l-2 py-1 pl-2",
                  task.overdue_days > 0 ? "border-destructive" : "border-border",
                )}
              >
                <p className="truncate text-foreground">{task.title}</p>
                <p
                  className={cn(
                    "truncate text-xs",
                    task.overdue_days > 0 ? "text-destructive" : "text-muted-foreground",
                  )}
                >
                  {TASK_KIND_LABELS[task.kind]} · {dueLabel(task.due_on, task.overdue_days)}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
      <Link
        href="/equipment?tab=tasks"
        className="mt-auto self-start font-medium text-primary hover:underline"
      >
        Sprzęt → Do zrobienia
      </Link>
    </div>
  )
}
