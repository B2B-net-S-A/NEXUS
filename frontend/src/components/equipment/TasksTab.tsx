"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useEquipmentTasks,
  useSetTaskStatus,
  type EquipmentHolder,
  type EquipmentTask,
} from "@/lib/api/equipment";
import { resolveViewState } from "@/lib/view-state";

import { HOLDER_KIND_LABELS, TASK_KIND_LABELS, dueLabel } from "./equipment-format";

interface TasksTabProps {
  onIssue: (holder: EquipmentHolder) => void;
  onReturn: (holder: EquipmentHolder) => void;
  onOpenProtocol: (protocolId: number) => void;
}

const GROUPS: { kind: EquipmentTask["kind"][]; title: string }[] = [
  { kind: ["wydanie", "zakup"], title: "Przygotuj" },
  { kind: ["podpis"], title: "Czeka na podpis" },
  { kind: ["zwrot"], title: "Zwroty" },
];

function holderOf(task: EquipmentTask): EquipmentHolder | null {
  const { kind, id, name } = task.holder;
  if (!kind || !id) return null;
  return { kind, id, name: name ?? "—", email: null, detail: HOLDER_KIND_LABELS[kind] };
}

/** „Do zrobienia”: zadania z wejść, startów kontraktów, odejść i niepodpisanych protokołów. */
export function TasksTab({ onIssue, onReturn, onOpenProtocol }: TasksTabProps) {
  const { showToast } = useToast();
  const tasks = useEquipmentTasks("otwarte");
  const setStatus = useSetTaskStatus();
  const rows = tasks.data ?? [];
  const state = resolveViewState({
    isLoading: tasks.isLoading,
    error: tasks.error,
    isSuccess: tasks.isSuccess,
    isEmpty: rows.length === 0,
  });

  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie zadań…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => tasks.refetch()} />;
  }
  if (state === "empty") {
    return (
      <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
        Nic do zrobienia. Zadania zakłada NEXUS: wejście i odejście pracownika, start i koniec
        współpracy konsultanta, niepodpisany protokół.
      </div>
    );
  }

  const close = (task: EquipmentTask, status: "zrobione" | "anulowane") =>
    setStatus.mutate(
      { id: task.id, status },
      {
        onSuccess: () =>
          showToast(status === "zrobione" ? "Zadanie odhaczone" : "Zadanie anulowane", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać."), "error"),
      },
    );

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {GROUPS.map((group) => {
        const items = rows.filter((task) => group.kind.includes(task.kind));
        return (
          <section key={group.title} aria-label={group.title} className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {group.title} <span className="tabular-nums">{items.length}</span>
            </h3>
            {items.length === 0 ? (
              <p className="text-sm text-muted-foreground">—</p>
            ) : (
              <ul className="space-y-2">
                {items.map((task) => {
                  const holder = holderOf(task);
                  return (
                    <li
                      key={task.id}
                      className="space-y-1.5 rounded-md border border-border bg-card px-3 py-2 text-sm"
                    >
                      <p className="font-medium">{task.title}</p>
                      <p
                        className={
                          task.overdue_days > 0
                            ? "text-xs text-destructive"
                            : "text-xs text-muted-foreground"
                        }
                      >
                        {TASK_KIND_LABELS[task.kind]} · {dueLabel(task.due_on, task.overdue_days)}
                        {typeof task.details.client_name === "string" && task.details.client_name
                          ? ` · ${task.details.client_name}`
                          : ""}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {task.kind === "wydanie" && holder ? (
                          <Button size="sm" onClick={() => onIssue(holder)}>
                            Wydaj
                          </Button>
                        ) : null}
                        {task.kind === "zwrot" && holder ? (
                          <Button size="sm" onClick={() => onReturn(holder)}>
                            Przyjmij zwrot
                          </Button>
                        ) : null}
                        {task.protocol ? (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => onOpenProtocol(task.protocol!.id)}
                          >
                            {task.protocol.number}
                          </Button>
                        ) : null}
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={setStatus.isPending}
                          onClick={() => close(task, "zrobione")}
                        >
                          Zrobione
                        </Button>
                        <Button
                          size="sm"
                          variant="quiet"
                          disabled={setStatus.isPending}
                          onClick={() => close(task, "anulowane")}
                        >
                          Nie dotyczy
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}
