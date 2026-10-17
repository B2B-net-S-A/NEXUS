"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2, Plus } from "lucide-react";

import { ContractOnboardingTab } from "@/components/ContractOnboardingTab";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import { useHrConfig } from "@/lib/api/hr";
import {
  ASSIGNEE_LABELS,
  AUDIENCE_ASSIGNEES,
  useAddContractEntryTask,
  useContractEntry,
  useCreateContractEntry,
  useUpdateTask,
  type AssigneeKind,
  type LifecycleTask,
} from "@/lib/api/hr-lifecycle";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { isNotFoundError, resolveViewState } from "@/lib/view-state";

import {
  createLabel,
  entrySteps,
  missingReasonText,
  taskSourceLabel,
  type EntryView,
} from "./entry-format";
import { WelcomeMailCard } from "./WelcomeMailCard";

const EQUIPMENT_LABELS = { ours: "od nas", client: "od klienta" } as const;

interface ContractEntryTabProps {
  contractId: number;
  /** Brak uprawnienia do edycji kontraktu — dotyczy starej listy onboardingu. */
  readOnly?: boolean;
}

/**
 * Zakładka „Wejście” kontraktu (etap 3, M6): jedna lista wejścia konsultanta
 * ze ścieżki, pakietu klienta i formy, karta „Z czego to powstało” i mail
 * powitalny. Kto co odhacza, mówi serwer (`can_toggle`). Wyłączony moduł
 * „Wejście i odejście” = stara lista onboardingu jak dotąd.
 */
export function ContractEntryTab({ contractId, readOnly = false }: ContractEntryTabProps) {
  const query = useContractEntry(contractId);
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
  });

  if (state === "loading") {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Wczytywanie…
      </p>
    );
  }
  if (isNotFoundError(query.error)) {
    // Moduł wyłączony (404 dla wszystkich poza adminem) — jak przed etapem 3.
    return <ContractOnboardingTab contractId={contractId} readOnly={readOnly} />;
  }
  if (state === "forbidden" || state === "error" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" ? "forbidden" : "error"}
        onRetry={() => query.refetch()}
      />
    );
  }
  const view = query.data as EntryView;
  if (!view.module_on) {
    return <ContractOnboardingTab contractId={contractId} readOnly={readOnly} />;
  }
  return (
    <div className="space-y-4">
      {view.case ? <EntryList view={view} /> : <MissingEntry view={view} />}
      {view.legacy_items > 0 ? (
        <Card className="space-y-2 p-4">
          <h3 className="text-sm font-semibold text-foreground">
            Wcześniejsza lista onboardingu
          </h3>
          <p className="text-xs text-muted-foreground">
            Z czasów przed ścieżkami wejścia — tylko do odczytu.
          </p>
          <ContractOnboardingTab contractId={contractId} readOnly />
        </Card>
      ) : null}
    </div>
  );
}

function MissingEntry({ view }: { view: EntryView }) {
  const { showToast } = useToast();
  const create = useCreateContractEntry(view.contract_id);
  return (
    <Card className="space-y-3 p-4">
      <p className="text-sm text-foreground">
        {missingReasonText(view.missing_reason, view.auto_create_on)}
      </p>
      {view.can_create ? (
        <Button
          size="sm"
          disabled={create.isPending}
          onClick={() =>
            create.mutate(undefined, {
              onSuccess: () => showToast("Lista wejścia założona", "success"),
              onError: (err) =>
                showToast(apiErrorMessage(err, "Nie udało się założyć listy wejścia."), "error"),
            })
          }
        >
          {createLabel(view.missing_reason)}
        </Button>
      ) : null}
    </Card>
  );
}

function EntryList({ view }: { view: EntryView }) {
  const data = view.case!;
  const live = data.status === "draft" || data.status === "active";
  const steps = entrySteps(data.tasks, data.start_date);
  const behind =
    data.template_version != null &&
    data.template_current_version != null &&
    data.template_version < data.template_current_version;
  const [adding, setAdding] = useState(false);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <ol className="flex flex-wrap gap-2" aria-label="Kroki wejścia">
            {steps.map((step) => (
              <li
                key={step.key}
                className="rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground"
              >
                <span className="font-medium text-foreground">{step.label}</span> {step.done} /{" "}
                {step.total}
              </li>
            ))}
          </ol>
          {view.can_add_task && live ? (
            <Button size="sm" variant="outline" onClick={() => setAdding((value) => !value)}>
              <Plus className="h-4 w-4" aria-hidden />
              Dodaj pozycję
            </Button>
          ) : null}
        </div>
        {adding ? (
          <AddTaskForm contractId={view.contract_id} onDone={() => setAdding(false)} />
        ) : null}
        {behind ? (
          <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
            Lista powstała z wersji {data.template_version} ścieżki, aktualna to wersja{" "}
            {data.template_current_version}. Nowe pozycje dociąga head back office w ścieżkach
            wejścia.
          </p>
        ) : null}
        <EntryTable tasks={data.tasks} live={live} />
      </div>
      <div className="space-y-4">
        <CompositionCard view={view} />
        <WelcomeMailCard contractId={view.contract_id} />
      </div>
    </div>
  );
}

function EntryTable({ tasks, live }: { tasks: LifecycleTask[]; live: boolean }) {
  const { showToast } = useToast();
  const update = useUpdateTask();
  if (tasks.length === 0) {
    return <p className="text-sm text-muted-foreground">Lista wejścia jest pusta.</p>;
  }
  const toggle = (task: LifecycleTask, checked: boolean) =>
    update.mutate(
      { taskId: task.id, status: checked ? "done" : "open" },
      {
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zapisać zadania."), "error"),
      },
    );
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <table className="w-full table-fixed text-sm">
        <thead>
          <tr className={CALM_ROW}>
            <th className="w-9 px-2 py-2" aria-label="Zrobione" />
            <th className={`${CALM_HEAD} px-2 py-2 text-left`}>Co</th>
            <th className={`${CALM_HEAD} w-32 px-2 py-2 text-left`}>Kto</th>
            <th className={`${CALM_HEAD} w-20 px-2 py-2 text-left`}>Termin</th>
            <th className={`${CALM_HEAD} w-32 px-2 py-2 text-left`}>Skąd</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => {
            const closed = task.status !== "open";
            const sub = [
              task.description,
              task.mirror?.note,
              task.requires_file ? "z plikiem" : null,
              task.required === false ? "nieobowiązkowe" : null,
              task.status === "skipped" ? "pominięte" : null,
              closed && task.done_by_name
                ? `${task.done_by_name}, ${formatIsoDatePl(task.done_at)}`
                : null,
            ].filter(Boolean);
            return (
              <tr key={task.id} className={`${CALM_ROW} align-top`}>
                <td className="px-2 py-2">
                  <Checkbox
                    checked={closed}
                    disabled={!live || !task.can_toggle || update.isPending}
                    onCheckedChange={(value) => toggle(task, value === true)}
                    aria-label={`${task.title} — ${closed ? "zrobione" : "do zrobienia"}`}
                  />
                </td>
                <td className="px-2 py-2">
                  <p className={closed ? "text-muted-foreground line-through" : "text-foreground"}>
                    {task.title}
                  </p>
                  {sub.length ? <p className={CALM_SUBLINE}>{sub.join(" · ")}</p> : null}
                </td>
                <td className="truncate px-2 py-2 text-muted-foreground">
                  {task.assignee_name ?? ASSIGNEE_LABELS[task.assignee_kind]}
                </td>
                <td className="px-2 py-2">
                  <span className={task.overdue ? "font-medium text-warning-muted-foreground" : ""}>
                    {task.due_date ? formatDayMonthPl(task.due_date) : "—"}
                  </span>
                </td>
                <td className="truncate px-2 py-2 text-muted-foreground">
                  {taskSourceLabel(task)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right text-foreground">{children}</span>
    </div>
  );
}

function CompositionCard({ view }: { view: EntryView }) {
  const data = view.case!;
  const { composition } = view;
  const fromClient = data.tasks.filter((task) => task.source === "client").length;
  const fromForm = data.tasks.filter((task) => task.source === "form").length;
  const me = useHrConfig().data?.me;
  const editsPaths = Boolean(me && (me.back_office_head || me.people_admin || me.is_admin));
  return (
    <Card className="space-y-1 p-4">
      <div className="flex items-baseline justify-between gap-2 pb-1">
        <h3 className="text-sm font-semibold text-foreground">Z czego to powstało</h3>
        {editsPaths ? (
          <Link href="/settings/hr" className="text-xs font-medium text-primary hover:underline">
            Edytuj ścieżkę
          </Link>
        ) : null}
      </div>
      <Fact label="Ścieżka">
        {data.template_name
          ? `${data.template_name} · wersja ${data.template_version ?? "—"}`
          : "bez ścieżki"}
      </Fact>
      <Fact label="Pakiet klienta">
        {view.pack_failed ? "nie wczytał się" : `${composition.client_name ?? "—"} (${fromClient})`}
      </Fact>
      <Fact label="Forma">
        {composition.employment_label ?? "—"} ({fromForm})
      </Fact>
      <Fact label="Sprzęt">
        {composition.equipment ? EQUIPMENT_LABELS[composition.equipment] : "nie ustalono"}
      </Fact>
      <Fact label="Opiekun">{composition.care_owner?.name ?? "bez opiekuna"}</Fact>
      <Fact label="Menedżer u klienta">{composition.client_manager ?? "—"}</Fact>
      {view.pack_failed ? (
        <p className="pt-1 text-xs text-warning-muted-foreground">
          Pakiet klienta nie wczytał się przy zakładaniu listy — jego pozycje dojdą same przy
          kolejnym przeglądzie startów.
        </p>
      ) : null}
    </Card>
  );
}

function AddTaskForm({ contractId, onDone }: { contractId: number; onDone: () => void }) {
  const { showToast } = useToast();
  const add = useAddContractEntryTask(contractId);
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState<AssigneeKind>("care_owner");
  const [due, setDue] = useState("");
  const submit = () => {
    if (!title.trim()) return;
    add.mutate(
      { title: title.trim(), category: "other", assignee_kind: assignee, due_date: due || null },
      {
        onSuccess: () => {
          showToast("Pozycja dodana", "success");
          onDone();
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się dodać pozycji."), "error"),
      },
    );
  };
  return (
    <Card className="grid items-end gap-2 p-3 sm:grid-cols-[1fr_150px_150px_auto]">
      <FormField label="Co" htmlFor="entry-task-title">
        <Input
          id="entry-task-title"
          value={title}
          maxLength={200}
          onChange={(event) => setTitle(event.target.value)}
        />
      </FormField>
      <FormField label="Kto">
        <Select value={assignee} onValueChange={(next) => setAssignee(next as AssigneeKind)}>
          <SelectTrigger aria-label="Kto">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {AUDIENCE_ASSIGNEES.consultant.map((key) => (
              <SelectItem key={key} value={key}>
                {ASSIGNEE_LABELS[key]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label="Termin" htmlFor="entry-task-due">
        <Input
          id="entry-task-due"
          type="date"
          value={due}
          onChange={(event) => setDue(event.target.value)}
        />
      </FormField>
      <Button size="sm" disabled={add.isPending || !title.trim()} onClick={submit}>
        Dodaj
      </Button>
    </Card>
  );
}
