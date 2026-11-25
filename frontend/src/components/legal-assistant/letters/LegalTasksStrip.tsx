"use client";

/**
 * Pasek zadań asystenta prawnego (część F): pod nagłówkiem listy kontraktów
 * i pod „Co się dzieje” na stronie kontraktu — w stylu `ContractHappeningStrip`.
 *
 * Zadania liczy serwer (`GET /api/legal/tasks`). Pusty stan = brak paska,
 * ale błąd zapytania mówi, że zadań nie udało się wczytać — nie wygląda
 * jak „nic do zrobienia”.
 */

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileWarning, Scale } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { dismissLegalTask, fetchLegalTasks, legalTasksQueryKey, type LegalTask } from "@/lib/legal-letters";
import { cn } from "@/lib/utils";

const TONE_BAR: Record<LegalTask["severity"], string> = {
  info: "bg-primary",
  warn: "bg-warning",
  gap: "bg-destructive",
};
const TONE_ICON: Record<LegalTask["severity"], string> = {
  info: "text-primary",
  warn: "text-warning",
  gap: "text-destructive",
};

export interface LegalTasksListProps {
  tasks: readonly LegalTask[];
  onDismiss?: (task: LegalTask) => void;
  dismissing?: string | null;
  /** Akcja zamiast linku (strona kontraktu otwiera panel bez przeładowania). */
  onAction?: (task: LegalTask) => void;
}

export function LegalTasksList({ tasks, onDismiss, dismissing, onAction }: LegalTasksListProps) {
  if (tasks.length === 0) return null;
  return (
    <section
      aria-label="Asystent prawny"
      className="overflow-hidden rounded-xl border border-border bg-card shadow-xs"
      data-testid="legal-tasks"
    >
      <ul className="divide-y divide-border/70">
        {tasks.map((task) => {
          const Icon = task.severity === "gap" ? FileWarning : Scale;
          return (
            <li key={task.key} className="relative flex flex-wrap items-center gap-x-3 gap-y-2 py-2 pl-4 pr-3" data-task={task.kind}>
              <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", TONE_BAR[task.severity])} />
              <Icon aria-hidden className={cn("size-4 shrink-0", TONE_ICON[task.severity])} />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-semibold leading-5 text-foreground">{task.title}</p>
                <p className="truncate text-[12px] leading-5 text-muted-foreground">{task.detail}</p>
              </div>
              <span className="text-[11px] text-muted-foreground">Asystent prawny</span>
              <div className="flex shrink-0 items-center gap-1.5">
                {onAction ? (
                  <Button size="sm" variant="outline" className="h-7 text-[12px]" onClick={() => onAction(task)} data-tour="legal-tasks.action">
                    {task.action_label}
                  </Button>
                ) : (
                  <Button asChild size="sm" variant="outline" className="h-7 text-[12px]" data-tour="legal-tasks.action">
                    <Link href={task.href}>{task.action_label}</Link>
                  </Button>
                )}
                {onDismiss && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 text-[12px]"
                    loading={dismissing === task.key}
                    disabled={dismissing != null}
                    onClick={() => onDismiss(task)}
                  >
                    Pomiń
                  </Button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export interface LegalTasksStripProps {
  /** Zawęża do jednego kontraktu (strona kontraktu). */
  contractId?: number;
  onAction?: (task: LegalTask) => void;
  enabled?: boolean;
}

export function LegalTasksStrip({ contractId, onAction, enabled = true }: LegalTasksStripProps) {
  const queryClient = useQueryClient();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useQuery({
    queryKey: legalTasksQueryKey(contractId),
    queryFn: () => fetchLegalTasks(contractId),
    enabled,
    staleTime: 60_000,
  });
  const dismiss = useMutation({
    mutationFn: (task: LegalTask) => dismissLegalTask(task.key),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["legal-tasks"] }),
  });

  if (query.isError) {
    return (
      <p
        role="alert"
        className="rounded-xl border border-destructive/30 bg-destructive-muted px-4 py-2 text-[12.5px] text-destructive"
        data-testid="legal-tasks-error"
      >
        {apiErrorMessage(query.error, "Nie udało się wczytać zadań asystenta prawnego.")}{" "}
        <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
          Spróbuj ponownie
        </button>
      </p>
    );
  }
  if (!query.isSuccess) return null;
  return (
    <>
      <LegalTasksList
        tasks={query.data}
        onAction={onAction}
        dismissing={dismiss.isPending ? (dismiss.variables?.key ?? null) : null}
        onDismiss={async (task) => {
          const ok = await askConfirm({
            title: "Pominąć zadanie asystenta?",
            description: `„${task.title}” zniknie z paska dla wszystkich. Pismo nadal napiszesz z „Napisz pismo” na stronie kontraktu.`,
            confirmLabel: "Pomiń",
          });
          if (ok) dismiss.mutate(task);
        }}
      />
      {dismiss.isError && (
        <p role="alert" className="text-[12px] text-destructive">
          {apiErrorMessage(dismiss.error, "Nie udało się pominąć zadania.")}
        </p>
      )}
      {confirmDialog}
    </>
  );
}
