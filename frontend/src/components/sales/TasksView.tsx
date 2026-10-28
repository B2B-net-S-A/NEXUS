"use client";

import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { apiErrorMessage } from "@/lib/api-error";
import {
  ACTIVITY_KIND_LABELS,
  useCompleteActivity,
  useCompleteTasks,
  useSalesTasks,
  type TaskBucket,
} from "@/lib/api/sales";
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
const KINDS = [
  { value: "", label: "Wszystko" },
  { value: "task", label: "Zadania" },
  { value: "call", label: "Telefony" },
] as const;
const PAGE = 100;

/**
 * Zadania i telefony handlowców: moje albo zespołu, w kubełkach terminu
 * (kalendarz firmy). Jak Task Center Atlasa — telefon z terminem to też
 * rzecz do zrobienia (audyt importu 28.10.2026).
 */
export function TasksView() {
  const [scope, setScope] = useState<"mine" | "team">("mine");
  const [bucket, setBucket] = useState<TaskBucket>("open");
  const [kind, setKind] = useState<"" | "task" | "call">("");
  const [limit, setLimit] = useState(PAGE);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const tasks = useSalesTasks({ scope, bucket, kind, limit });
  const complete = useCompleteActivity();
  const completeMany = useCompleteTasks();
  const user = useAuthStore((s) => s.user);
  const canEdit = hasPermission(user, "sales_edit");
  const { showError, showSuccess } = useToast();
  const items = tasks.data?.items ?? [];
  const total = tasks.data?.total ?? 0;
  const state = resolveViewState({
    isLoading: tasks.isLoading,
    error: tasks.error,
    isSuccess: tasks.isSuccess,
    isEmpty: items.length === 0,
  });
  const resetPage = () => {
    setLimit(PAGE);
    setSelected(new Set());
  };
  const toggle = (id: number) =>
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedRadio
          size="sm"
          label="Czyje zadania"
          options={[
            { value: "mine", label: "Moje" },
            { value: "team", label: "Zespół" },
          ]}
          value={scope}
          onChange={(value) => {
            setScope(value as "mine" | "team");
            resetPage();
          }}
        />
        <SegmentedRadio
          size="sm"
          label="Termin"
          options={BUCKETS}
          value={bucket}
          onChange={(value) => {
            setBucket(value as TaskBucket);
            resetPage();
          }}
        />
        <SegmentedRadio
          size="sm"
          label="Rodzaj"
          options={KINDS.map((option) => ({ ...option }))}
          value={kind}
          onChange={(value) => {
            setKind(value as "" | "task" | "call");
            resetPage();
          }}
        />
        {tasks.isSuccess && <span className="text-sm text-muted-foreground">{total} pozycji</span>}
        {canEdit && selected.size > 0 && (
          <Button
            size="sm"
            className="ml-auto"
            loading={completeMany.isPending}
            onClick={() =>
              completeMany.mutate([...selected], {
                onSuccess: (result) => {
                  showSuccess(`Oznaczono jako zrobione: ${result.updated}.`);
                  setSelected(new Set());
                },
                onError: (error) => showError(apiErrorMessage(error, "Nie udało się zamknąć zadań.")),
              })
            }
          >
            Zrobione ({selected.size})
          </Button>
        )}
      </div>
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie zadań…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => void tasks.refetch()} />
      ) : state === "empty" ? (
        <EmptyState
          icon={CheckCircle2}
          title={bucket === "done" ? "Nic jeszcze nie zrobiono" : "Brak zadań"}
          description="Zadania i telefony dodajesz w historii firmy albo szansy."
        />
      ) : (
        <>
          <ul className="divide-y divide-border rounded-lg border border-border bg-card">
            {items.map((task) => (
              <li key={task.id} className="flex items-start gap-3 px-4 py-3">
                {canEdit && !task.done_at && (
                  <input
                    type="checkbox"
                    className="mt-1"
                    aria-label={`Zaznacz: ${task.subject ?? ACTIVITY_KIND_LABELS[task.kind]}`}
                    checked={selected.has(task.id)}
                    onChange={() => toggle(task.id)}
                  />
                )}
                <div className="min-w-0 flex-1 text-sm">
                  <p className="font-medium text-foreground">
                    {task.kind !== "task" && (
                      <span className="mr-1.5 text-muted-foreground">{ACTIVITY_KIND_LABELS[task.kind]} ·</span>
                    )}
                    {task.subject ?? "Bez tematu"}
                  </p>
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
          {items.length < total && (
            <div className="flex justify-center">
              <Button size="sm" variant="outline" onClick={() => setLimit((value) => value + PAGE)}>
                Pokaż więcej ({total - items.length})
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
