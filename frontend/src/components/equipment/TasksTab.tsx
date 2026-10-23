"use client";

import { useState, type ReactNode } from "react";
import { Mail, MoreHorizontal } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useEquipmentSummary,
  useEquipmentTasks,
  useRemindTaskHolder,
  useSetTaskStatus,
  type EquipmentHolder,
  type EquipmentTask,
} from "@/lib/api/equipment";
import { formatDayMonthPl, formatWeekdayDayPl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import {
  AGENDA_TITLES,
  CATEGORY_PLURAL,
  HOLDER_KIND_LABELS,
  TASK_KIND_LABELS,
  agendaDue,
  agendaGroups,
  kitForTask,
  matchesAgendaFilter,
  returnReminderMailHref,
  stockCoverage,
  taskContext,
  taskTitle,
  weekPlan,
  type AgendaFilter,
  type IssueKitKey,
} from "./equipment-format";
import { HolderAvatar, KitIcons } from "./equipment-visuals";
import { useProtocolQuickActions } from "./useProtocolQuickActions";

interface TasksTabProps {
  onIssue: (holder: EquipmentHolder, kit: IssueKitKey | null) => void;
  onReturn: (holder: EquipmentHolder) => void;
  onOpenProtocol: (protocolId: number) => void;
}

const FILTERS: { key: AgendaFilter; label: string }[] = [
  { key: "all", label: "Wszystko" },
  { key: "przygotuj", label: "Przygotuj" },
  { key: "podpis", label: "Podpis" },
  { key: "zwrot", label: "Zwroty" },
];

function holderOf(task: EquipmentTask): EquipmentHolder | null {
  const { kind, id, name } = task.holder;
  if (!kind || !id) return null;
  return { kind, id, name: name ?? "—", email: null, detail: HOLDER_KIND_LABELS[kind] };
}

function kindBadge(task: EquipmentTask, overdue: boolean) {
  const variant =
    task.kind === "podpis"
      ? "warning"
      : task.kind === "zwrot"
        ? overdue
          ? "danger"
          : "neutral"
        : "info";
  return <Badge variant={variant}>{TASK_KIND_LABELS[task.kind]}</Badge>;
}

/**
 * „Do zrobienia”: agenda wg terminu (Po terminie → Dziś → Później) z jedną
 * główną akcją na zadanie, obok „Czy starczy na wydania?” i plan tygodnia.
 */
export function TasksTab({ onIssue, onReturn, onOpenProtocol }: TasksTabProps) {
  const { showToast } = useToast();
  const tasks = useEquipmentTasks("otwarte");
  const summary = useEquipmentSummary();
  const setStatus = useSetTaskStatus();
  const remind = useRemindTaskHolder();
  const quick = useProtocolQuickActions();
  const [filter, setFilter] = useState<AgendaFilter>("all");
  const [mailTo, setMailTo] = useState<{ task: EquipmentTask; email: string } | null>(null);
  const today = warsawToday();
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
        Nic do zrobienia. Zadania zakłada NEXUS: wejście i odejście osoby, start i koniec
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

  const sendReminder = (task: EquipmentTask) =>
    remind.mutate(task.id, {
      onSuccess: (result) => {
        if (result.channel === "mail" && result.email) {
          setMailTo({ task, email: result.email });
        } else {
          showToast(`Przypomnienie wysłane: ${task.holder.name ?? "osoba"} (dzwonek i mail)`, "success");
        }
      },
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przypomnieć."), "error"),
    });

  const visible = rows.filter((task) => matchesAgendaFilter(task, filter));
  const groups = agendaGroups(visible, today);

  const renderActions = (task: EquipmentTask, overdue: boolean): ReactNode => {
    const holder = holderOf(task);
    const protocol = task.protocol;
    let main: ReactNode = null;
    let extra: ReactNode = null;
    if (task.kind === "wydanie" && holder) {
      main = (
        <Button size="sm" onClick={() => onIssue(holder, kitForTask(task)?.key ?? null)}>
          Wydaj
        </Button>
      );
    } else if (task.kind === "zwrot" && holder) {
      if (overdue) {
        extra = (
          <Button size="sm" variant="outline" disabled={remind.isPending} onClick={() => sendReminder(task)}>
            Przypomnij
          </Button>
        );
      }
      main = (
        <Button size="sm" variant={overdue ? "primary" : "outline"} onClick={() => onReturn(holder)}>
          Przyjmij zwrot
        </Button>
      );
    } else if (task.kind === "podpis" && protocol) {
      main =
        protocol.status === "podpisany" ? (
          <Button size="sm" disabled={quick.busy} onClick={() => quick.confirmSigned(protocol)}>
            Potwierdź
          </Button>
        ) : (
          <Button size="sm" variant="outline" disabled={quick.busy} onClick={() => quick.sendLink(protocol)}>
            Wyślij link ponownie
          </Button>
        );
    } else {
      main = (
        <Button size="sm" variant="outline" disabled={setStatus.isPending} onClick={() => close(task, "zrobione")}>
          Zrobione
        </Button>
      );
    }
    return (
      <div className="flex shrink-0 items-center justify-end gap-1.5">
        {extra}
        {main}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="icon-sm" variant="ghost" aria-label={`Więcej akcji: ${taskTitle(task)}`}>
              <MoreHorizontal className="h-4 w-4" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {protocol ? (
              <DropdownMenuItem onSelect={() => onOpenProtocol(protocol.id)}>
                Protokół {protocol.number}
              </DropdownMenuItem>
            ) : null}
            {task.kind === "zwrot" && holder && !overdue ? (
              <DropdownMenuItem disabled={remind.isPending} onSelect={() => sendReminder(task)}>
                Przypomnij o zwrocie
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuItem disabled={setStatus.isPending} onSelect={() => close(task, "zrobione")}>
              Zrobione
            </DropdownMenuItem>
            <DropdownMenuItem disabled={setStatus.isPending} onSelect={() => close(task, "anulowane")}>
              Nie dotyczy
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  };

  const composition = (task: EquipmentTask) => {
    const kit = kitForTask(task);
    if (kit) {
      return (
        <KitIcons
          label={`${kit.title}: ${kit.slots.map((slot) => slot.label).join(", ")}`}
          categories={kit.slots.map((slot) => ({
            category: slot.category,
            modelName: slot.modelName ? slot.label : null,
          }))}
        />
      );
    }
    const categories = task.protocol?.categories ?? [];
    return (
      <KitIcons
        label={`W protokole: ${categories.length} poz.`}
        categories={categories.map((category) => ({ category }))}
      />
    );
  };

  return (
    <div className="flex flex-wrap items-start gap-4">
      <section
        aria-label="Agenda zadań"
        className="min-w-0 flex-[999_1_640px] overflow-hidden rounded-lg border border-border bg-card"
      >
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div role="group" aria-label="Rodzaj zadania" className="flex flex-wrap gap-1.5">
            {FILTERS.map(({ key, label }) => {
              const count = rows.filter((task) => matchesAgendaFilter(task, key)).length;
              return (
                <button
                  key={key}
                  type="button"
                  aria-pressed={filter === key}
                  onClick={() => setFilter(key)}
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-md border px-2.5 text-sm font-medium",
                    filter === key
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-border bg-card hover:bg-muted",
                  )}
                >
                  {label} <span className="tabular-nums opacity-70">{count}</span>
                </button>
              );
            })}
          </div>
          <span className="text-xs text-muted-foreground">wg terminu</span>
        </div>
        {groups.length === 0 ? (
          <p className="border-t border-border px-4 py-6 text-sm text-muted-foreground">
            Nic w tym filtrze.
          </p>
        ) : (
          groups.map((group) => (
            <div key={group.bucket} role="group" aria-label={AGENDA_TITLES[group.bucket]}>
              <div className="flex items-center gap-2 border-t border-border bg-muted/40 px-4 py-2">
                <span
                  className={cn(
                    "text-[11px] font-semibold uppercase tracking-wide",
                    group.bucket === "overdue" ? "text-destructive" : "text-muted-foreground",
                  )}
                >
                  {group.bucket === "today"
                    ? `Dziś · ${formatWeekdayDayPl(today)}`
                    : AGENDA_TITLES[group.bucket]}
                </span>
                <Badge size="sm" variant={group.bucket === "overdue" ? "danger" : "neutral"}>
                  {group.tasks.length}
                </Badge>
              </div>
              <ul>
                {group.tasks.map((task) => {
                  const overdue = group.bucket === "overdue";
                  const reminded =
                    typeof task.details.reminded_on === "string" ? task.details.reminded_on : null;
                  return (
                    <li
                      key={task.id}
                      className={cn(
                        "grid grid-cols-[88px_minmax(0,1fr)] items-center gap-x-3 gap-y-2 border-t border-border px-4 py-2.5 sm:grid-cols-[88px_minmax(0,1fr)_auto]",
                        overdue && "bg-destructive-muted/30",
                      )}
                    >
                      <div>
                        {kindBadge(task, overdue)}
                        <p
                          className={cn(
                            "mt-1 text-xs",
                            overdue ? "font-medium text-destructive" : "text-muted-foreground",
                          )}
                        >
                          {agendaDue(task.due_on, today)}
                        </p>
                      </div>
                      <div className="flex min-w-0 items-center gap-3">
                        {task.holder.name ? (
                          <HolderAvatar name={task.holder.name} kind={task.holder.kind} />
                        ) : null}
                        {/* Przy 1280 z paskiem bocznym ikony składu schodzą pod tekst, żeby
                            tytuł z nazwiskiem się zmieścił (prod 20.10); tytuł nie ucina się
                            w pół słowa, najwyżej łamie się na dwie linie. */}
                        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1.5">
                          <div className="min-w-0 flex-[1_1_18rem]">
                            <p className="line-clamp-2 break-words font-medium" title={taskTitle(task)}>
                              {taskTitle(task)}
                            </p>
                            <p className="truncate text-xs text-muted-foreground">
                              {[
                                taskContext(task),
                                reminded ? `przypomniano ${formatDayMonthPl(reminded)}` : "",
                              ]
                                .filter(Boolean)
                                .join(" · ") || " "}
                            </p>
                          </div>
                          {composition(task)}
                        </div>
                      </div>
                      <div className="col-span-2 sm:col-span-1">{renderActions(task, overdue)}</div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))
        )}
      </section>

      <aside className="flex min-w-0 flex-[1_1_320px] flex-col gap-4">
        <CoverageCard tasks={rows} freeByCategory={summary.data?.free_by_category} />
        <WeekCard tasks={rows} today={today} />
      </aside>

      {mailTo ? (
        <AppModal
          open
          onOpenChange={(next) => {
            if (!next) setMailTo(null);
          }}
          title={`Przypomnij: ${mailTo.task.holder.name ?? "osoba"}`}
          description={
            mailTo.task.holder.kind === "user"
              ? "Dzwonek w NEXUSIE nie wyszedł (powiadomienia wyciszone albo przypomnienie było już dziś) — przypomnienie wysyłasz ze swojej poczty."
              : "Ta osoba nie ma konta w NEXUSIE — przypomnienie wysyłasz ze swojej poczty."
          }
          footer={
            <>
              <Button variant="ghost" onClick={() => setMailTo(null)}>
                Zamknij
              </Button>
              <Button asChild>
                <a href={returnReminderMailHref(mailTo.email, mailTo.task.due_on)}>
                  <Mail className="h-4 w-4" aria-hidden />
                  Otwórz w poczcie
                </a>
              </Button>
            </>
          }
        >
          <p className="text-sm">
            Wiadomość do <span className="font-medium">{mailTo.email}</span> z prośbą o zwrot
            sprzętu. Przypomnienie zapisaliśmy przy zadaniu.
          </p>
        </AppModal>
      ) : null}
      {quick.dialogs}
    </div>
  );
}

function CoverageCard({
  tasks,
  freeByCategory,
}: {
  tasks: EquipmentTask[];
  freeByCategory: Parameters<typeof stockCoverage>[1] | undefined;
}) {
  const rows = freeByCategory ? stockCoverage(tasks, freeByCategory) : [];
  return (
    <section aria-label="Czy starczy na wydania?" className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div>
        <h3 className="text-sm font-semibold">Czy starczy na wydania?</h3>
        <p className="text-xs text-muted-foreground">Zestawy do przygotowania vs. wolne na stanie</p>
      </div>
      {!freeByCategory ? (
        <p className="text-sm text-muted-foreground">Liczby chwilowo niedostępne.</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nie ma zestawów do przygotowania.</p>
      ) : (
        <div
          role="table"
          aria-label="Zestawy do przygotowania vs. wolne"
          className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-x-2.5 gap-y-1.5 text-sm"
        >
          <div role="row" className="contents text-[11px] text-muted-foreground">
            <span role="columnheader">
              <span className="sr-only">Rodzaj</span>
            </span>
            <span role="columnheader" className="text-right text-[11px] text-muted-foreground">
              potrzeba
            </span>
            <span role="columnheader" className="text-right text-[11px] text-muted-foreground">
              wolne
            </span>
            <span role="columnheader">
              <span className="sr-only">Ocena</span>
            </span>
          </div>
          {rows.map((row) => (
            <div
              key={row.category}
              role="row"
              className="contents"
            >
              <span role="cell" className="truncate" title={CATEGORY_PLURAL[row.category]}>
                {CATEGORY_PLURAL[row.category]}
              </span>
              <span role="cell" className="text-right font-semibold tabular-nums">
                {row.needed}
              </span>
              <span role="cell" className="text-right tabular-nums text-muted-foreground">
                {row.free}
              </span>
              <span role="cell" className="text-right">
                {row.short > 0 ? (
                  <Badge variant="warning">brakuje {row.short}</Badge>
                ) : (
                  <Badge variant="success">starczy</Badge>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function WeekCard({ tasks, today }: { tasks: EquipmentTask[]; today: string }) {
  const plan = weekPlan(tasks, today);
  return (
    <section aria-label="Ten tydzień w recepcji" className="space-y-2.5 rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-semibold">Ten tydzień w recepcji</h3>
      <ol className="grid grid-cols-5 gap-1.5 text-center text-xs">
        {plan.days.map((day) => (
          <li
            key={day.date}
            aria-label={`${day.label} ${formatDayMonthPl(day.date)}: ${day.count}`}
            className={cn(
              "rounded-md py-2",
              day.isToday ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
            )}
          >
            <span className="block">{day.label}</span>
            <span className="block text-base font-semibold tabular-nums text-foreground">{day.count}</span>
          </li>
        ))}
      </ol>
      <p className="text-xs text-muted-foreground">
        {plan.next.count > 0 && plan.next.first
          ? `Następny tydzień: ${plan.next.count} (od ${formatWeekdayDayPl(plan.next.first)})`
          : "Następny tydzień: nic zaplanowanego"}
      </p>
    </section>
  );
}
