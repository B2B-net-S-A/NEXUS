"use client";

import Link from "next/link";
import { useState, type FormEvent, type ReactNode } from "react";
import { Bot, Check, ExternalLink } from "lucide-react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useAddChangeTask,
  useComplianceChange,
  useDecideChange,
  useUpdateChangeTask,
  type ChangeDetail as ChangeDetailData,
  type ChangeStage,
  type ChangeStatus,
  type LawChangeListItem,
} from "@/lib/api/compliance";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import {
  CLASS_HINT,
  CLASS_LABEL,
  GATE_LABEL,
  ROLE_LABEL,
  STAGES,
  STAGE_LABEL,
  STATUS_LABEL,
  URGENCY_LABEL,
  URGENCY_TONE,
  dateLine,
  eventLine,
  formatDay,
  formatMoment,
  itemsByClass,
  probeLine,
  safeExternalUrl,
  safeInternalLink,
} from "./compliance-model";

const NOTE_MAX = 1000;
const TASK_MAX = 200;

interface ChangesViewProps {
  changes: LawChangeListItem[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function ChangesView({ changes, selectedId, onSelect }: ChangesViewProps) {
  const selected = changes.find((change) => change.id === selectedId) ?? changes[0];
  return (
    <div className="grid min-w-0 gap-3.5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
      <ul
        aria-label="Zmiany w prawie"
        className="min-w-0 divide-y divide-border/70 self-start overflow-hidden rounded-lg border border-border bg-card"
      >
        {changes.map((change) => {
          const active = change.id === selected?.id;
          const headline = change.probes.find((probe) => probe.text || probe.value != null);
          return (
            <li key={change.id}>
              <button
                type="button"
                onClick={() => onSelect(change.id)}
                aria-current={active ? "true" : undefined}
                className={cn(
                  "grid w-full gap-1 px-3.5 py-2.5 text-left transition-colors",
                  active ? "bg-primary/5" : "hover:bg-muted/40",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <span className={cn("text-[13px] leading-5 text-foreground", active ? "font-semibold" : "font-medium")}>
                    {change.title}
                  </span>
                  <StatusDot
                    tone={change.status === "not_applicable" || change.status === "done" ? "neutral" : URGENCY_TONE[change.urgency]}
                    className="shrink-0"
                  >
                    {change.status === "not_applicable" || change.status === "done"
                      ? STATUS_LABEL[change.status]
                      : URGENCY_LABEL[change.urgency]}
                  </StatusDot>
                </div>
                <div className="flex flex-wrap gap-x-2 text-[11px] leading-4 text-muted-foreground">
                  <span>{dateLine(change)}</span>
                  <span aria-hidden>·</span>
                  <span>{STAGE_LABEL[change.stage] ?? change.stage}</span>
                  {change.verified_sources === 0 ? (
                    <StatusDot tone="warning">Numer aktu lub druku do potwierdzenia</StatusDot>
                  ) : null}
                  <span aria-hidden>·</span>
                  <span>{STATUS_LABEL[change.status] ?? change.status}</span>
                  {change.tasks.open ? (
                    <>
                      <span aria-hidden>·</span>
                      <span>zadania: {change.tasks.open} otwarte</span>
                    </>
                  ) : null}
                </div>
                {headline ? (
                  <div className="text-xs leading-4 text-foreground/90">
                    <span className="font-medium text-primary">U nas: </span>
                    {probeLine(headline)}
                  </div>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
      {selected ? <ChangeDetail id={selected.id} /> : null}
    </div>
  );
}

function StageTrack({ stage }: { stage: ChangeStage }) {
  const current = STAGES.findIndex((item) => item.value === stage);
  return (
    <ol className="flex flex-wrap items-center gap-1 text-[11px]" aria-label="Etap legislacji">
      {STAGES.map((item, index) => (
        <li key={item.value} className="flex items-center gap-1">
          <span
            aria-current={index === current ? "step" : undefined}
            className={cn(
              "rounded px-1.5 py-0.5",
              index < current && "text-muted-foreground",
              index === current && "bg-primary/10 font-semibold text-foreground",
              index > current && "text-muted-foreground/60",
            )}
          >
            {index < current ? <Check className="mr-0.5 inline h-3 w-3" aria-hidden /> : null}
            {item.label}
          </span>
          {index < STAGES.length - 1 ? <span className="text-muted-foreground/50">›</span> : null}
        </li>
      ))}
    </ol>
  );
}

function SectionTitle({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h3 className={cn("mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground", className)}>
      {children}
    </h3>
  );
}

function ChangeDetail({ id }: { id: number }) {
  const detail = useComplianceChange(id);
  const state = resolveViewState({
    isLoading: detail.isLoading,
    isError: detail.isError,
    error: detail.error,
    isSuccess: detail.isSuccess,
    isEmpty: false,
  });
  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie zmiany…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return (
      <QueryStateNotice
        state={state}
        description={state === "not_found" ? "Tej zmiany już nie ma na liście." : undefined}
        onRetry={() => detail.refetch()}
      />
    );
  }
  const data = detail.data;
  if (!data || !data.enabled) return null;
  return <ChangeCard data={data} />;
}

function ChangeCard({ data }: { data: ChangeDetailData }) {
  const { change, items, tasks, events, probes } = data;
  const { showToast } = useToast();
  const { askReason, confirmDialog } = useConfirmV2();
  const decide = useDecideChange();

  const setStatus = async (status: ChangeStatus, note?: string) => {
    try {
      await decide.mutateAsync({ id: change.id, status, note });
      showToast(`Zapisano: ${STATUS_LABEL[status]}.`);
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się zapisać decyzji."), "error");
    }
  };

  const notApplicable = async () => {
    const reason = await askReason({
      title: "Ta zmiana nas nie dotyczy?",
      description: "Powód trafi do dziennika decyzji. Kolejny bieg Analityka nie zmieni tej decyzji.",
      confirmLabel: "Zapisz „Nie dotyczy”",
      field: {
        label: "Powód",
        placeholder: "Np. nie zatrudniamy na umowę o pracę w tej grupie",
        minLength: 1,
        maxLength: NOTE_MAX,
      },
    });
    if (reason) await setStatus("not_applicable", reason);
  };

  const groups = itemsByClass(items);

  return (
    <article className="min-w-0 rounded-lg border border-border bg-card" aria-label={change.title}>
      <header className="grid gap-2 border-b border-border/70 px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="min-w-0 text-[15px] font-semibold leading-5">{change.title}</h2>
          {change.legal_ref ? <span className="text-xs text-muted-foreground">{change.legal_ref}</span> : null}
        </div>
        <StageTrack stage={change.stage} />
        {items.some((item) => item.gate === "verified") ? (
          <StatusDot tone="success">Numer aktu lub druku potwierdzony w API Sejmu</StatusDot>
        ) : (
          <StatusDot tone="warning">
            Brak źródła z numerem potwierdzonym w API Sejmu. Sprawdź podstawę wskazanego etapu.
          </StatusDot>
        )}
        <p className="flex flex-wrap gap-x-2 text-[11px] text-muted-foreground">
          {change.effective_on ? <span>Wchodzi w życie: {formatDay(change.effective_on)}</span> : null}
          {change.deadline ? <span>Termin dla nas: {formatDay(change.deadline)}</span> : null}
          <span>Dla: {change.roles.map((role) => ROLE_LABEL[role] ?? role).join(", ") || "—"}</span>
          <span>Status: {STATUS_LABEL[change.status]}</span>
        </p>
      </header>

      <div className="grid gap-3.5 px-4 py-3 text-[13px] leading-5">
        {change.summary.length ? (
          <section>
            <SectionTitle>W skrócie</SectionTitle>
            <ul className="list-disc space-y-0.5 pl-4">
              {change.summary.map((line, index) => (
                <li key={index}>{line}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {probes.length ? (
          <section className="rounded-md border border-primary/25 bg-primary/5 px-3 py-2">
            <SectionTitle className="text-primary">Co to znaczy dla nas (dane z NEXUSA)</SectionTitle>
            <ul className="space-y-1">
              {probes.map((probe) => {
                const href = safeInternalLink(probe.link);
                return (
                  <li key={probe.key} className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span>
                      <span className="font-medium text-primary">U nas: </span>
                      {probeLine(probe)}
                    </span>
                    {href ? (
                      <Link href={href} className="shrink-0 text-xs font-medium text-primary hover:underline">
                        Pokaż →
                      </Link>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}

        <TasksSection changeId={change.id} tasks={tasks} />

        {groups.length ? (
          <section>
            <SectionTitle>Źródła</SectionTitle>
            <ul className="space-y-1.5">
              {groups.flatMap((group) =>
                group.items.map((item) => {
                  const href = safeExternalUrl(item.url);
                  return (
                    <li key={item.id} className="flex items-baseline gap-2">
                      <span
                        className={cn(
                          "w-[5.5rem] shrink-0 text-[11px]",
                          item.klass === "practice" ? "text-info" : "text-muted-foreground",
                        )}
                        title={CLASS_HINT[item.klass]}
                      >
                        {CLASS_LABEL[item.klass]}
                      </span>
                      <span className="grid min-w-0 flex-1 gap-0.5">
                        {href ? (
                          <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-foreground hover:text-primary hover:underline"
                          >
                            {item.title}
                            <ExternalLink className="ml-1 inline h-3 w-3 text-muted-foreground" aria-hidden />
                          </a>
                        ) : (
                          <span>{item.title}</span>
                        )}
                        {item.quote ? <span className="text-xs italic text-muted-foreground">„{item.quote}”</span> : null}
                        <span className="text-[11px] text-muted-foreground">
                          {[item.act_ref, item.print_no ? `druk ${item.print_no}` : null, GATE_LABEL[item.gate]]
                            .filter(Boolean)
                            .join(" · ")}
                        </span>
                      </span>
                      <span className="shrink-0 text-[11px] text-muted-foreground">{formatDay(item.published)}</span>
                    </li>
                  );
                }),
              )}
            </ul>
          </section>
        ) : null}

        {change.decision_note ? (
          <section className="rounded-md bg-muted/40 px-3 py-2 text-xs">
            <span className="font-semibold">
              Decyzja{change.decided_by ? ` · ${change.decided_by}` : ""}
              {change.decided_at ? `, ${formatMoment(change.decided_at)}` : ""}:{" "}
            </span>
            {change.decision_note}
          </section>
        ) : null}

        {events.length ? (
          <section>
            <SectionTitle>Dziennik decyzji</SectionTitle>
            <ol className="space-y-0.5 text-xs">
              {events.map((event) => (
                <li key={event.id} className="flex flex-wrap gap-x-2">
                  <span className="shrink-0 tabular-nums text-muted-foreground">{formatMoment(event.at)}</span>
                  <span className="shrink-0 text-muted-foreground">
                    {event.bot ? "Grok Bot" : (event.by ?? "NEXUS")}
                  </span>
                  <span className="min-w-0">
                    {eventLine(event)}
                    {event.note ? ` — ${event.note}` : ""}
                  </span>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
      </div>

      <footer className="flex flex-wrap items-center gap-2 border-t border-border/70 px-4 py-2.5">
        {change.status !== "in_progress" ? (
          <Button size="sm" onClick={() => setStatus("in_progress")} disabled={decide.isPending}>
            Dotyczy nas
          </Button>
        ) : null}
        {change.status !== "not_applicable" ? (
          <Button size="sm" variant="outline" onClick={notApplicable} disabled={decide.isPending}>
            Nie dotyczy (z powodem)
          </Button>
        ) : null}
        {change.status !== "done" ? (
          <Button size="sm" variant="ghost" onClick={() => setStatus("done")} disabled={decide.isPending}>
            <Check className="mr-1 h-3.5 w-3.5" aria-hidden />
            Zrobione
          </Button>
        ) : null}
      </footer>
      {confirmDialog}
    </article>
  );
}

function TasksSection({ changeId, tasks }: { changeId: number; tasks: ChangeDetailData["tasks"] }) {
  const { showToast } = useToast();
  const toggle = useUpdateChangeTask();
  const add = useAddChangeTask(changeId);
  const [text, setText] = useState("");
  const [due, setDue] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const clean = text.trim();
    if (!clean) return;
    try {
      await add.mutateAsync({ text: clean, due_on: due || null });
      setText("");
      setDue("");
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się dodać zadania."), "error");
    }
  };

  const setDone = async (id: number, done: boolean) => {
    try {
      await toggle.mutateAsync({ id, done });
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się zapisać zadania."), "error");
    }
  };

  return (
    <section>
      <SectionTitle>Do zrobienia</SectionTitle>
      <div className="rounded-md border border-border">
        {tasks.length ? (
          <ul className="divide-y divide-border/60">
            {tasks.map((task) => (
              <li key={task.id} className="flex items-center gap-2 px-2.5 py-1.5">
                <Checkbox
                  checked={task.done}
                  onCheckedChange={(next) => setDone(task.id, next === true)}
                  disabled={toggle.isPending}
                  aria-label={task.done ? `Otwórz ponownie: ${task.text}` : `Zrobione: ${task.text}`}
                />
                <span className={cn("min-w-0 flex-1", task.done && "text-muted-foreground line-through")}>
                  {task.text}
                </span>
                <span className="flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
                  {task.source === "bot" ? <Bot className="h-3 w-3" aria-label="od Analityka" /> : null}
                  {[task.assignee?.name, task.role ? ROLE_LABEL[task.role] : null, task.due_on ? formatDay(task.due_on) : null]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-2.5 py-1.5 text-xs text-muted-foreground">Bez zadań.</p>
        )}
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2 border-t border-border/60 px-2.5 py-1.5">
          <input
            aria-label="Nowe zadanie"
            value={text}
            maxLength={TASK_MAX}
            onChange={(event) => setText(event.target.value)}
            placeholder="Dopisz zadanie…"
            className="h-8 w-0 min-w-40 flex-1 rounded-md border border-border bg-background px-2 text-[13px] placeholder:text-muted-foreground focus:border-primary focus:outline-hidden"
          />
          <input
            type="date"
            aria-label="Termin zadania"
            value={due}
            onChange={(event) => setDue(event.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-[13px] text-foreground focus:border-primary focus:outline-hidden"
          />
          <Button size="sm" variant="outline" type="submit" disabled={!text.trim()} loading={add.isPending}>
            Dodaj
          </Button>
        </form>
      </div>
    </section>
  );
}
