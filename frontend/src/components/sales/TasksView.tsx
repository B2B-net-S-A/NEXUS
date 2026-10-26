"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useCompleteActivity, useSalesTasks, type TaskBucket } from "@/lib/api/sales";
import { formatDateTimePl } from "@/lib/date-pl";
import { hasPermission } from "@/lib/permissions";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

const BUCKETS: { value: TaskBucket; label: string }[] = [
  { value: "open", label: "Do zrobienia" },
  { value: "overdue", label: "Po terminie" },
  { value: "today", label: "Na dziś" },
  { value: "done", label: "Zrobione" },
];

/** Zadania handlowców: moje albo zespołu, w kubełkach terminu (kalendarz firmy). */
export function TasksView() {
  const [scope, setScope] = useState<"mine" | "team">("mine");
  const [bucket, setBucket] = useState<TaskBucket>("open");
  const tasks = useSalesTasks(scope, bucket);
  const complete = useCompleteActivity();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { showError } = useToast();
  const items = tasks.data ?? [];
  const state = resolveViewState({
    isLoading: tasks.isLoading,
    error: tasks.error,
    isSuccess: tasks.isSuccess,
    isEmpty: items.length === 0,
  });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <TabbedNav
          dense
          ariaLabel="Czyje zadania"
          tabs={[
            { value: "mine", label: "Moje" },
            { value: "team", label: "Zespół" },
          ]}
          value={scope}
          onValueChange={(value) => setScope(value as "mine" | "team")}
        />
        <TabbedNav
          dense
          ariaLabel="Termin"
          tabs={BUCKETS}
          value={bucket}
          onValueChange={(value) => setBucket(value as TaskBucket)}
        />
      </div>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie zadań…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void tasks.refetch()} />
      ) : state === "empty" ? (
        <EmptyState
          icon={CheckCircle2}
          title={bucket === "done" ? "Nic jeszcze nie zrobiono" : "Brak zadań"}
          description="Zadania dodajesz w historii firmy albo szansy."
        />
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {items.map((task) => (
            <li key={task.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
              <div className="min-w-0 text-sm">
                <p className="font-medium text-foreground">{task.subject}</p>
                <p className={`text-xs ${task.overdue ? "text-destructive" : "text-muted-foreground"}`}>
                  {task.done_at
                    ? `zrobione ${formatDateTimePl(task.done_at)}`
                    : task.due_at
                      ? `termin ${formatDateTimePl(task.due_at)}`
                      : "bez terminu"}
                  {scope === "team" && task.assignee ? ` · ${task.assignee.name}` : ""}
                </p>
                <p className="text-xs">
                  {task.opportunity ? (
                    <Link href={`/sales/opportunities/${task.opportunity.id}`} className="text-primary hover:underline">
                      {task.company?.name ? `${task.company.name} · ` : ""}
                      {task.opportunity.name}
                    </Link>
                  ) : task.company ? (
                    <Link href={`/sales/companies/${task.company.id}`} className="text-primary hover:underline">
                      {task.company.name}
                    </Link>
                  ) : null}
                </p>
              </div>
              {canEdit && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    complete.mutate(
                      { id: task.id, reopen: Boolean(task.done_at) },
                      { onError: (error) => showError(apiErrorMessage(error, "Nie udało się zmienić zadania.")) },
                    )
                  }
                >
                  {task.done_at ? "Przywróć" : "Zrobione"}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
