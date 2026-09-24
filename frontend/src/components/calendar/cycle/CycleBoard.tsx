"use client";

import { useState } from "react";

import { EmptyState } from "@/components/ds/EmptyState";
import {
  STEP_GROUPS,
  STEP_ORDER,
  STEP_OWNER,
  STEP_TITLES,
  TODO_LABELS,
  actionForItem,
  candidateLabel,
  countdownLabel,
  formatDayLabel,
  formatTime,
  pairContext,
  pairKey,
  todosByPair,
  type CycleAction,
  type CycleItem,
  type StepKey,
  type TodoEntry,
} from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

/** Kolor fazy nad kolumnami: niebieski = umawianie, fiolet = prep, bursztyn = rozmowa. */
const GROUP_TONE: Record<(typeof STEP_GROUPS)[number]["key"], string> = {
  arrange: "bg-info-muted text-info-muted-foreground",
  prepare: "bg-primary/10 text-primary",
  interview: "bg-warning-muted text-warning-muted-foreground",
};

const URGENT_TODOS = new Set<TodoEntry["kind"]>(["call_now", "debrief_overdue", "prep_weak"]);

/** Krok, o którym mówi zadanie — w jego kolumnie plakietka byłaby powtórzeniem nagłówka. */
const TODO_STEP: Partial<Record<TodoEntry["kind"], StepKey[]>> = {
  slots_missing: ["slots"],
  slots_pick: ["choice"],
  slots_confirm: ["choice"],
  prep_missing: ["prep"],
  prep2_missing: ["prep2"],
  call_now: ["call", "debrief"],
  debrief_overdue: ["call", "debrief"],
};

/** Szerokość kolumny: pusta zwinięta do paska, reszta dzieli miejsce. */
const COLLAPSED = "104px";
const OPEN = "minmax(200px,1fr)";
const OPEN_MOBILE = "80%";

/**
 * Tablica 7 kroków — każda para stoi w kolumnie swojego bieżącego kroku.
 * Odpowiada na pytania „gdzie utknął który kandydat?” i „co mam zrobić?”:
 * karta niesie najpilniejsze zadanie pary i przycisk. Klik w nazwisko
 * otwiera panel kandydata (kroki, prepy, Teams, pytania klienta).
 */
export function CycleBoard({
  items,
  todos,
  now,
  canManageSlots,
  onAction,
  onSelect,
}: {
  items: CycleItem[];
  todos: TodoEntry[];
  now: Date;
  canManageSlots: boolean;
  onAction: (a: CycleAction) => void;
  onSelect: (key: string) => void;
}) {
  const [collapseEmpty, setCollapseEmpty] = useState(true);
  const columns = new Map<StepKey, CycleItem[]>(STEP_ORDER.map((k) => [k, []]));
  for (const item of items) {
    if (item.current_step) columns.get(item.current_step)?.push(item);
  }
  const todoMap = todosByPair(todos);
  // Zadanie pary, której nie ma na żadnej kolumnie (cykl zamknięty, a np.
  // prep bez nagrania) — nie może zniknąć razem z dawną Agendą.
  const onBoard = new Set(items.filter((i) => i.current_step).map(pairKey));
  const orphanTodos = todos.filter((t) => !onBoard.has(pairKey(t)));

  if (items.every((i) => !i.current_step) && orphanTodos.length === 0) {
    return (
      <EmptyState
        title="Żaden kandydat nie jest w trakcie rozmów u klienta"
        description="Tablica zapełni się, gdy DL doda terminy od klienta albo kandydat trafi na etap „Rozmowa z klientem”."
      />
    );
  }

  const isCollapsed = (key: StepKey) => collapseEmpty && (columns.get(key)?.length ?? 0) === 0;
  const template = (mobile: boolean) =>
    STEP_ORDER.map((k) => (isCollapsed(k) ? COLLAPSED : mobile ? OPEN_MOBILE : OPEN)).join(" ");

  return (
    <div className="flex flex-col gap-3" data-help="calendar.board">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <label className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={collapseEmpty}
            onChange={(e) => setCollapseEmpty(e.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          Zwiń puste kroki
        </label>
      </div>

      {orphanTodos.length > 0 ? (
        <OrphanTodos todos={orphanTodos} onSelect={onSelect} />
      ) : null}

      <div className="overflow-x-auto pb-2">
        <div
          className="grid min-w-full gap-x-2.5 gap-y-2 [grid-template-columns:var(--cols-mobile)] sm:[grid-template-columns:var(--cols)]"
          style={
            {
              "--cols": template(false),
              "--cols-mobile": template(true),
            } as React.CSSProperties
          }
          role="list"
          aria-label="Tablica kroków rozmów u klienta"
        >
          {STEP_GROUPS.map((g) => (
            <div
              key={g.key}
              aria-hidden
              style={{ gridColumn: `span ${g.steps.length}` }}
              className={cn(
                "truncate rounded-md px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wide",
                GROUP_TONE[g.key],
              )}
            >
              {g.label}
            </div>
          ))}
          {STEP_ORDER.map((key) => {
            const list = columns.get(key) ?? [];
            const hot = key === "call" && list.length > 0;
            const n = STEP_ORDER.indexOf(key) + 1;
            if (isCollapsed(key)) {
              return (
                <section
                  key={key}
                  role="listitem"
                  aria-label={`${STEP_TITLES[key]} — pusto`}
                  className="flex min-w-0 flex-col gap-1 rounded-xl bg-muted/60 p-2.5"
                >
                  <h3 className="text-xs font-bold leading-tight text-foreground">
                    {n}. {STEP_TITLES[key]}
                  </h3>
                  <span className="text-[11px] leading-tight text-muted-foreground">{STEP_OWNER[key]}</span>
                  <span className="text-lg font-bold tabular-nums text-muted-foreground">0</span>
                </section>
              );
            }
            return (
              <section
                key={key}
                role="listitem"
                aria-label={STEP_TITLES[key]}
                className={cn(
                  "flex min-w-0 flex-col gap-2 rounded-xl p-2.5",
                  hot ? "bg-destructive/10" : "bg-muted/60",
                )}
              >
                <header className="px-0.5 pb-1">
                  <div className="flex items-center justify-between gap-2">
                    <h3 className={cn("text-sm font-bold", hot && "text-destructive")}>
                      {n}. {STEP_TITLES[key]}
                    </h3>
                    <span className="text-xs font-semibold tabular-nums text-muted-foreground">
                      {list.length}
                    </span>
                  </div>
                  <div className="text-[11px] text-muted-foreground">{STEP_OWNER[key]}</div>
                </header>
                {list.map((item) => (
                  <BoardCard
                    key={pairKey(item)}
                    item={item}
                    column={key}
                    hot={hot}
                    todos={todoMap.get(pairKey(item)) ?? []}
                    now={now}
                    canManageSlots={canManageSlots}
                    onAction={onAction}
                    onSelect={onSelect}
                  />
                ))}
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function BoardCard({
  item,
  column,
  hot,
  todos,
  now,
  canManageSlots,
  onAction,
  onSelect,
}: {
  item: CycleItem;
  column: StepKey;
  hot: boolean;
  todos: TodoEntry[];
  now: Date;
  canManageSlots: boolean;
  onAction: (a: CycleAction) => void;
  onSelect: (key: string) => void;
}) {
  const step = item.steps.find((s) => s.key === column);
  const action = actionForItem(item, { canManageSlots });
  const overdue = step?.state === "overdue";
  // Najpilniejsze zadanie pary (np. „Prep słaby”), o ile mówi coś ponad kolumnę.
  const todo = todos.find((t) => !TODO_STEP[t.kind]?.includes(column));
  const urgentTodo = todo ? todo.urgent || URGENT_TODOS.has(todo.kind) : false;
  return (
    <article
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border bg-card p-3",
        overdue || hot || urgentTodo ? "border-destructive/40" : "border-border",
      )}
      data-testid="cycle-board-card"
    >
      <button
        type="button"
        onClick={() => onSelect(pairKey(item))}
        className="text-left"
        aria-label={`${candidateLabel(item)} — pokaż kroki i szczegóły`}
      >
        <div className="text-sm font-semibold text-foreground hover:text-primary">{candidateLabel(item)}</div>
        <div className="truncate text-xs text-muted-foreground" title={pairContext(item)}>
          {pairContext(item)}
        </div>
      </button>
      {todo ? (
        <div
          className={cn(
            "rounded-md px-2 py-1 text-xs font-semibold",
            urgentTodo ? "bg-destructive/10 text-destructive" : "bg-muted text-foreground/80",
          )}
        >
          {TODO_LABELS[todo.kind]}
        </div>
      ) : null}
      {step?.at || step?.meta ? (
        <div
          className={cn(
            "text-xs font-semibold tabular-nums",
            step?.at && "font-mono",
            overdue || hot ? "text-destructive" : "text-foreground/80",
          )}
        >
          {step?.at
            ? column === "call"
              ? `do ${formatTime(step.at)} · ${countdownLabel(step.at, now)}`
              : `${formatDayLabel(step.at, now)} ${formatTime(step.at)}`
            : step?.meta}
        </div>
      ) : null}
      {action ? (
        <button
          type="button"
          onClick={() => onAction(action.action)}
          className={cn(
            "h-8 rounded-md text-xs font-semibold",
            hot
              ? "bg-destructive text-destructive-foreground hover:bg-destructive/90"
              : "bg-primary/10 text-primary hover:bg-primary/15",
          )}
        >
          {action.label}
        </button>
      ) : null}
    </article>
  );
}

function OrphanTodos({ todos, onSelect }: { todos: TodoEntry[]; onSelect: (key: string) => void }) {
  return (
    <section
      aria-label="Sprawy poza tablicą"
      className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card px-3 py-2.5 text-sm"
    >
      <span className="font-semibold text-foreground">Po rozmowie:</span>
      {todos.map((t) => (
        <button
          key={`${t.kind}-${pairKey(t)}`}
          type="button"
          onClick={() => onSelect(pairKey(t))}
          className="rounded-md bg-muted px-2 py-1 text-xs hover:bg-muted/70"
        >
          {TODO_LABELS[t.kind]} · {candidateLabel(t)}
        </button>
      ))}
    </section>
  );
}
