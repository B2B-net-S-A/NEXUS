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
import { personInitials } from "@/components/hr/people/hr-format";

import { groupTasksByOwner } from "./lifecycle-format";

interface LifecycleTaskListProps {
  tasks: LifecycleTask[];
  /** Sprawa w toku — dopiero wtedy zadania się odhacza. */
  editable: boolean;
  /** Pogrupuj wg wykonawcy, zrobione na końcu (odejście, makieta 19.10.2026). */
  grouped?: boolean;
}

/** Zadania sprawy: kto, do kiedy, odhaczenie (serwer mówi, komu wolno). */
export function LifecycleTaskList({ tasks, editable, grouped = false }: LifecycleTaskListProps) {
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
  const row = (task: LifecycleTask, showWho: boolean) => (
    <TaskRow
      key={task.id}
      task={task}
      showWho={showWho}
      disabled={!editable || !task.can_toggle || update.isPending}
      onToggle={(checked) => toggle(task, checked)}
    />
  );

  if (grouped) {
    return (
      <div className="space-y-3">
        {groupTasksByOwner(tasks, ASSIGNEE_LABELS).map((group) => (
          <section key={group.key} aria-label={group.label}>
            <div className="flex items-center gap-1.5 pb-0.5">
              {group.person ? (
                <span
                  aria-hidden
                  className="grid h-5 w-5 place-items-center rounded-full bg-primary/10 text-[8px] font-semibold text-primary"
                >
                  {personInitials(group.person)}
                </span>
              ) : null}
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {group.label}
              </span>
            </div>
            <ul className="divide-y divide-border/60">
              {group.tasks.map((task) => row(task, group.key === "done"))}
            </ul>
          </section>
        ))}
      </div>
    );
  }

  return <ul className="divide-y divide-border/60">{tasks.map((task) => row(task, true))}</ul>;
}

function TaskRow({
  task,
  showWho,
  disabled,
  onToggle,
}: {
  task: LifecycleTask;
  showWho: boolean;
  disabled: boolean;
  onToggle: (checked: boolean) => void;
}) {
  const closed = task.status !== "open";
  const who = task.assignee_name ?? ASSIGNEE_LABELS[task.assignee_kind];
  return (
    <li className="flex items-start gap-3 py-2">
      <Checkbox
        checked={closed}
        disabled={disabled}
        onCheckedChange={(value) => onToggle(value === true)}
        aria-label={`${task.title} — ${closed ? "zrobione" : "do zrobienia"}`}
        className="mt-0.5"
      />
      <div className="min-w-0 flex-1 text-sm">
        <p className={closed ? "text-muted-foreground line-through" : "text-foreground"}>
          {task.title}
        </p>
        <p className="text-xs text-muted-foreground">
          {[
            showWho ? who : null,
            CATEGORY_LABELS[task.category],
            task.due_date ? `do ${formatWeekdayDayPl(task.due_date)}` : null,
            task.status === "skipped" ? "pominięte" : null,
            closed && task.done_by_name ? `${task.done_by_name}, ${formatIsoDatePl(task.done_at)}` : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {task.note ? <p className="mt-0.5 text-xs text-muted-foreground">{task.note}</p> : null}
      </div>
      {task.overdue ? (
        <span className="shrink-0 rounded-full bg-warning-muted px-2 py-0.5 text-[11px] font-medium text-warning-muted-foreground">
          po terminie
        </span>
      ) : null}
    </li>
  );
}
