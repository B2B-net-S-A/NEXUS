"use client";

import { useMemo, useState } from "react";
import { Phone, Video } from "lucide-react";

import { EmptyState } from "@/components/ds/EmptyState";
import {
  AGENDA_LABELS,
  TODO_ACTIONS,
  TODO_LABELS,
  actionForItem,
  actionForTodo,
  candidateLabel,
  countdownLabel,
  debriefAvailable,
  debriefAvailableFromLabel,
  formatSlot,
  formatTime,
  groupAgendaByDay,
  interviewStartFor,
  pairContext,
  pairKey,
  relativeLabel,
  upcomingAgenda,
  type AgendaEntry,
  type CycleAction,
  type CycleItem,
  type CycleOverview,
  type TodoEntry,
} from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

import { CycleStepper } from "./CycleStepper";
import { ClientQuestions } from "./ClientQuestions";

const CHIP: Record<AgendaEntry["kind"], string> = {
  prep: "bg-primary/10 text-primary",
  prep2: "bg-primary/10 text-primary",
  interview: "bg-warning-muted text-warning-muted-foreground",
  call: "bg-success-muted text-success-muted-foreground",
  tentative: "bg-muted text-muted-foreground border border-dashed border-warning",
};

const DOT: Record<TodoEntry["kind"], string> = {
  call_now: "bg-destructive",
  debrief_overdue: "bg-destructive",
  slots_pick: "bg-warning",
  slots_confirm: "bg-warning",
  prep_missing: "bg-primary",
  prep2_missing: "bg-primary",
  slots_missing: "bg-muted-foreground",
};

export interface AgendaViewProps {
  data: CycleOverview;
  now: Date;
  canManageSlots: boolean;
  onAction: (action: CycleAction) => void;
  /** Para wybrana z linku (`?cycle=`) albo kliknięciem. */
  selectedKey: string | null;
  onSelect: (key: string) => void;
}

/** Widok A: „Do zrobienia” · agenda dziś/jutro/tydzień · karta kandydata. */
export function AgendaView({
  data,
  now,
  canManageSlots,
  onAction,
  selectedKey,
  onSelect,
}: AgendaViewProps) {
  const [showAll, setShowAll] = useState(false);
  const days = useMemo(
    () => groupAgendaByDay(upcomingAgenda(data.agenda, now), now),
    [data.agenda, now],
  );
  const visibleDays = showAll ? days : days.slice(0, 3);
  const callNow = data.todos.filter((t) => t.kind === "call_now");
  const otherTodos = data.todos.filter((t) => t.kind !== "call_now");
  // Bez wyboru z linku: najpierw telefon „teraz”, potem PIERWSZA pozycja
  // z listy „Do zrobienia” — ta sama, którą użytkownik widzi na górze.
  // `data.items[0]` ma inną kolejność niż lista zadań i wskazywał osobę
  // ze środka listy.
  const firstTodoKey = [...callNow, ...otherTodos].map(pairKey)[0] ?? null;
  const selected =
    data.items.find((i) => pairKey(i) === selectedKey) ??
    data.items.find((i) => i.current_step === "call") ??
    (firstTodoKey ? data.items.find((i) => pairKey(i) === firstTodoKey) : undefined) ??
    data.items[0] ??
    null;
  const selectedPairKey = selected ? pairKey(selected) : null;

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)_360px]">
      {/* Do zrobienia */}
      <section aria-labelledby="cycle-todo-h" className="flex flex-col gap-3 min-w-0">
        <h2 id="cycle-todo-h" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Do zrobienia
        </h2>
        {callNow.map((t) => (
          <CallNowCard key={pairKey(t)} todo={t} now={now} items={data.items} onAction={onAction} />
        ))}
        {otherTodos.length > 0 ? (
          <ul className="rounded-xl border border-border bg-card divide-y divide-border overflow-hidden">
            {otherTodos.map((t) => {
              const action = actionForTodo(t, data.items);
              const allowed =
                action &&
                !((action.type === "add_slots" || action.type === "confirm") && !canManageSlots);
              return (
                <li
                  key={`${t.kind}-${pairKey(t)}`}
                  className={cn(
                    "flex items-start gap-3 px-3.5 py-3",
                    pairKey(t) === selectedPairKey && "bg-primary/5",
                  )}
                  aria-current={pairKey(t) === selectedPairKey ? "true" : undefined}
                >
                  <span className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", DOT[t.kind])} aria-hidden />
                  <button
                    type="button"
                    onClick={() => onSelect(pairKey(t))}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="text-xs font-semibold text-muted-foreground">{TODO_LABELS[t.kind]}</div>
                    <div className="truncate text-sm font-semibold text-foreground">{candidateLabel(t)}</div>
                    <div className="line-clamp-2 text-xs text-muted-foreground">
                      {pairContext(t)}
                      {t.due ? ` · ${relativeLabel(t.due, now)}` : ""}
                    </div>
                  </button>
                  {allowed && action ? (
                    <button
                      type="button"
                      onClick={() => onAction(action)}
                      className="shrink-0 h-8 rounded-md border border-border bg-card px-2.5 text-xs font-semibold hover:bg-muted"
                    >
                      {TODO_ACTIONS[t.kind]}
                    </button>
                  ) : null}
                </li>
              );
            })}
          </ul>
        ) : null}
        {data.todos.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border px-4 py-5 text-sm text-muted-foreground">
            Nic nie czeka. Nowe zadania pojawią się, gdy DL doda terminy od klienta albo skończy się rozmowa.
          </p>
        ) : null}
      </section>

      {/* Agenda */}
      <section
        aria-labelledby="cycle-agenda-h"
        className="min-w-0 rounded-2xl border border-border bg-card overflow-hidden flex flex-col"
      >
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <h2 id="cycle-agenda-h" className="text-sm font-bold">
            Agenda
          </h2>
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <Legend className="bg-primary" label="Prep" />
            <Legend className="bg-warning" label="Rozmowa u klienta" />
            <Legend className="bg-success" label="Telefon po" />
          </div>
        </div>
        {days.length === 0 ? (
          <div className="p-6">
            <EmptyState
              title="Brak prepów i rozmów u klienta w najbliższych dniach"
              description="Tu pojawią się prepy, rozmowy kandydatów u klienta i telefony po nich. Spotkania z Outlooka znajdziesz w zakładce „Tydzień”."
            />
          </div>
        ) : (
          <div>
            {visibleDays.map((day) => (
              <div key={day.key}>
                <div className="bg-muted/40 px-4 py-2 text-xs font-bold uppercase tracking-wide text-muted-foreground">
                  {day.label}
                </div>
                <ul className="divide-y divide-border">
                  {day.entries.map((e) => (
                    <AgendaRow
                      key={`${e.kind}-${e.event_id ?? e.slot_request_id}-${e.start}`}
                      entry={e}
                      interviewStart={
                        e.kind === "call" && e.event_id != null
                          ? interviewStartFor(data, e.event_id)
                          : undefined
                      }
                      now={now}
                      selected={pairKey(e) === selectedPairKey}
                      onSelect={() => onSelect(pairKey(e))}
                      onAction={onAction}
                    />
                  ))}
                </ul>
              </div>
            ))}
            {days.length > 3 ? (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="w-full border-t border-border px-4 py-3 text-xs font-semibold text-primary hover:bg-muted/40"
              >
                {showAll ? "Pokaż mniej" : `Pokaż kolejne dni (${days.length - 3})`}
              </button>
            ) : null}
          </div>
        )}
      </section>

      {/* Karta kandydata — bez par w cyklu nie ma czego pokazać (pusta karta
          „Wybierz kandydata” czytała się jak zepsuty panel). */}
      {selected ? (
      <aside
        aria-label="Wybrany kandydat"
        className="min-w-0 rounded-2xl border border-border bg-card p-4 lg:col-span-2 xl:col-span-1"
      >
        <CandidateCycleCard
          item={selected}
          canManageSlots={canManageSlots}
          onAction={onAction}
        />
      </aside>
      ) : null}
    </div>
  );
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={cn("h-2 w-2 rounded-full", className)} aria-hidden />
      {label}
    </span>
  );
}

function CallNowCard({
  todo,
  now,
  items,
  onAction,
}: {
  todo: TodoEntry;
  now: Date;
  items: CycleItem[];
  onAction: (a: CycleAction) => void;
}) {
  const action = actionForTodo(todo, items);
  return (
    <div
      role="alert"
      className="flex flex-col gap-2 rounded-xl border border-destructive/30 bg-destructive/10 p-3.5"
      data-testid="cycle-call-now"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-sm font-bold text-destructive">
          <Phone className="h-4 w-4" aria-hidden />
          Zadzwoń teraz
        </span>
        {todo.due ? (
          <span className="font-mono text-xs font-semibold text-destructive tabular-nums">
            {countdownLabel(todo.due, now)}
          </span>
        ) : null}
      </div>
      <div className="text-base font-semibold text-foreground">{candidateLabel(todo)}</div>
      <div className="text-xs text-muted-foreground">
        Rozmowa u klienta się skończyła · {pairContext(todo)}
      </div>
      {action ? (
        <button
          type="button"
          onClick={() => onAction(action)}
          className="h-9 self-start rounded-md bg-destructive px-3 text-sm font-semibold text-destructive-foreground hover:bg-destructive/90"
        >
          Zapisz debrief
        </button>
      ) : null}
    </div>
  );
}

function AgendaRow({
  entry,
  interviewStart,
  now,
  selected,
  onSelect,
  onAction,
}: {
  entry: AgendaEntry;
  /** Początek rozmowy, po której jest ten telefon — debrief dopiero od niego. */
  interviewStart?: string;
  now: Date;
  selected: boolean;
  onSelect: () => void;
  onAction: (a: CycleAction) => void;
}) {
  const past =
    entry.kind === "call"
      ? entry.done
      : new Date(entry.end ?? entry.start).getTime() < now.getTime();
  const range = entry.end ? `${formatTime(entry.start)}–${formatTime(entry.end)}` : formatTime(entry.start);
  const inCallWindow =
    entry.kind === "call" &&
    !entry.done &&
    now.getTime() >= new Date(entry.start).getTime() &&
    entry.end != null &&
    now.getTime() <= new Date(entry.end).getTime();
  return (
    <li
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3",
        past && "opacity-60",
        selected && "bg-primary/5",
        inCallWindow && "bg-destructive/5 shadow-[inset_3px_0_0_hsl(var(--destructive))]",
      )}
    >
      <div className="w-24 shrink-0 font-mono text-sm font-semibold tabular-nums">{range}</div>
      <span className={cn("shrink-0 rounded-md px-2 py-1 text-xs font-semibold", CHIP[entry.kind])}>
        {AGENDA_LABELS[entry.kind]}
      </span>
      <button type="button" onClick={onSelect} className="min-w-[160px] flex-1 text-left">
        <div className="text-sm font-semibold text-foreground">{candidateLabel(entry)}</div>
        <div className="text-xs text-muted-foreground">{pairContext(entry)}</div>
      </button>
      <div className="flex shrink-0 items-center gap-2">
        {entry.online_meeting_url && !past ? (
          <a
            href={entry.online_meeting_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 items-center gap-1 rounded-md bg-primary/10 px-2.5 text-xs font-semibold text-primary hover:bg-primary/15"
          >
            <Video className="h-3.5 w-3.5" aria-hidden />
            Dołącz
          </a>
        ) : null}
        {entry.kind === "call" && !entry.done && entry.event_id != null ? (
          debriefAvailable(interviewStart, now) ? (
            <button
              type="button"
              onClick={() =>
                onAction({ type: "debrief", pair: entry, eventId: entry.event_id as number })
              }
              className="h-8 rounded-md border border-border px-2.5 text-xs font-semibold hover:bg-muted"
            >
              Debrief
            </button>
          ) : (
            <>
              <span
                id={`debrief-hint-${entry.event_id}`}
                className="text-xs text-muted-foreground"
              >
                {debriefAvailableFromLabel(interviewStart as string, now)}
              </span>
              <button
                type="button"
                disabled
                aria-describedby={`debrief-hint-${entry.event_id}`}
                title={debriefAvailableFromLabel(interviewStart as string, now)}
                className="h-8 cursor-not-allowed rounded-md border border-border px-2.5 text-xs font-semibold opacity-50"
              >
                Debrief
              </button>
            </>
          )
        ) : null}
        {entry.kind === "call" && entry.done ? (
          <span className="text-xs text-success-muted-foreground">debrief zapisany</span>
        ) : null}
        {entry.kind !== "call" && entry.event_id != null ? (
          <button
            type="button"
            onClick={() => onAction({ type: "open_event", eventId: entry.event_id as number })}
            className="h-8 rounded-md px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            Szczegóły
          </button>
        ) : null}
      </div>
    </li>
  );
}

export function CandidateCycleCard({
  item,
  canManageSlots,
  onAction,
}: {
  item: CycleItem;
  canManageSlots: boolean;
  onAction: (a: CycleAction) => void;
}) {
  const current = actionForItem(item, { canManageSlots });
  const req = item.slot_request;
  return (
    <div className="flex flex-col gap-4" data-testid="cycle-candidate-card">
      <div>
        <div className="text-xs text-muted-foreground">Wybrany kandydat</div>
        <div className="text-lg font-bold text-foreground">{candidateLabel(item)}</div>
        <div className="text-sm text-muted-foreground">{pairContext(item)}</div>
      </div>
      <CycleStepper
        steps={item.steps}
        action={
          current
            ? { stepKey: current.stepKey, label: current.label, onClick: () => onAction(current.action) }
            : null
        }
      />
      {req && req.status !== "cancelled" && req.status !== "confirmed" ? (
        <div className="rounded-lg bg-muted/50 p-3 text-xs">
          <div className="mb-1 font-semibold text-foreground">Terminy od klienta</div>
          <ul className="space-y-0.5">
            {req.slots.map((s, i) => (
              <li key={s.start} className={cn(i === req.chosen_index && "font-semibold text-primary")}>
                {formatSlot(s)}
                {i === req.chosen_index ? " · wybrany" : ""}
              </li>
            ))}
          </ul>
          {req.note ? <p className="mt-1.5 text-muted-foreground">Notatka DL: {req.note}</p> : null}
        </div>
      ) : null}
      <ClientQuestions jobId={item.job_id} clientName={item.client_name} />
    </div>
  );
}
