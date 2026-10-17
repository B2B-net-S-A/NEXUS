"use client";

import { useToast } from "@/components/Toast";
import { Checkbox } from "@/components/ui/checkbox";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ASSIGNEE_LABELS,
  CATEGORY_LABELS,
  useUpdateTask,
  type LifecycleTask,
} from "@/lib/api/hr-lifecycle";
import { formatIsoDatePl, formatWeekdayDayPl } from "@/lib/date-pl";

interface LifecycleTaskListProps {
  tasks: LifecycleTask[];
  /** Sprawa w toku — dopiero wtedy zadania się odhacza. */
  editable: boolean;
}

/** Zadania sprawy: kto, do kiedy, odhaczenie (serwer mówi, komu wolno). */
export function LifecycleTaskList({ tasks, editable }: LifecycleTaskListProps) {
  const { showToast } = useToast();
  const update = useUpdateTask();

  if (tasks.length === 0) {
    return <p className="text-sm text-muted-foreground">Bez zadań.</p>;
  }

  const toggle = (task: LifecycleTask, checked: boolean) => {
    update.mutate(
      { taskId: task.id, status: checked ? "done" : "open" },
      {
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zapisać zadania."), "error"),
      },
    );
  };

  return (
    <ul className="divide-y divide-border/60">
      {tasks.map((task) => {
        const closed = task.status !== "open";
        const who = task.assignee_name ?? ASSIGNEE_LABELS[task.assignee_kind];
        const disabled = !editable || !task.can_toggle || update.isPending;
        return (
          <li key={task.id} className="flex items-start gap-3 py-2">
            <Checkbox
              checked={closed}
              disabled={disabled}
              onCheckedChange={(value) => toggle(task, value === true)}
              aria-label={`${task.title} — ${closed ? "zrobione" : "do zrobienia"}`}
              className="mt-0.5"
            />
            <div className="min-w-0 flex-1 text-sm">
              <p className={closed ? "text-muted-foreground line-through" : "text-foreground"}>
                {task.title}
              </p>
              <p className="text-xs text-muted-foreground">
                {who} · {CATEGORY_LABELS[task.category]}
                {task.due_date ? ` · do ${formatWeekdayDayPl(task.due_date)}` : ""}
                {task.status === "skipped" ? " · pominięte" : ""}
                {closed && task.done_by_name
                  ? ` · ${task.done_by_name}, ${formatIsoDatePl(task.done_at)}`
                  : ""}
              </p>
              {task.note ? (
                <p className="mt-0.5 text-xs text-muted-foreground">{task.note}</p>
              ) : null}
            </div>
            {task.overdue ? (
              <span className="shrink-0 rounded-full bg-warning-muted px-2 py-0.5 text-[11px] font-medium text-warning-muted-foreground">
                po terminie
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
