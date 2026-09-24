"use client";

import { EmptyState } from "@/components/ds/EmptyState";
import {
  STEP_ORDER,
  STEP_OWNER,
  STEP_TITLES,
  actionForItem,
  candidateLabel,
  formatDayLabel,
  formatTime,
  pairContext,
  pairKey,
  type CycleAction,
  type CycleItem,
  type StepKey,
} from "@/lib/interview-cycle";
import { cn } from "@/lib/utils";

/**
 * Widok B: tablica 7 kroków — każda para stoi w kolumnie swojego bieżącego
 * kroku. Odpowiada na pytanie DL-a „gdzie utknął który kandydat?”.
 * Pary z zamkniętym cyklem (debrief zapisany) nie stoją nigdzie.
 */
export function CycleBoard({
  items,
  canManageSlots,
  onAction,
  onSelect,
}: {
  items: CycleItem[];
  canManageSlots: boolean;
  onAction: (a: CycleAction) => void;
  onSelect: (key: string) => void;
}) {
  const columns = new Map<StepKey, CycleItem[]>(STEP_ORDER.map((k) => [k, []]));
  for (const item of items) {
    if (item.current_step) columns.get(item.current_step)?.push(item);
  }
  if (items.every((i) => !i.current_step)) {
    return (
      <EmptyState
        title="Żaden kandydat nie jest w trakcie rozmów u klienta"
        description="Tablica zapełni się, gdy DL doda terminy od klienta albo kandydat trafi na etap „Rozmowa z klientem”."
      />
    );
  }
  return (
    <div
      // Na telefonie kolumna zajmuje ~80% szerokości (widać sąsiednią — wiadomo,
      // że tablica przewija się w bok), a na dotyku kolumny się dociągają.
      className="grid gap-2.5 overflow-x-auto pb-2 grid-cols-[repeat(7,80%)] sm:grid-cols-[repeat(7,minmax(180px,1fr))] pointer-coarse:snap-x pointer-coarse:snap-mandatory"
      role="list"
      aria-label="Tablica kroków rozmów u klienta"
    >
      {STEP_ORDER.map((key) => {
        const list = columns.get(key) ?? [];
        const hot = key === "call" && list.length > 0;
        return (
          <section
            key={key}
            role="listitem"
            aria-label={STEP_TITLES[key]}
            className={cn(
              "flex min-w-0 snap-start flex-col gap-2 rounded-xl p-2.5",
              hot ? "bg-destructive/10" : "bg-muted/60",
            )}
          >
            <header className="px-0.5 pb-1">
              <div className="flex items-center justify-between">
                <h3 className={cn("text-sm font-bold", hot && "text-destructive")}>
                  {STEP_ORDER.indexOf(key) + 1}. {STEP_TITLES[key]}
                </h3>
                <span className="text-xs font-semibold text-muted-foreground tabular-nums">
                  {list.length}
                </span>
              </div>
              <div className="text-[11px] text-muted-foreground">{STEP_OWNER[key]}</div>
            </header>
            {list.map((item) => {
              const step = item.steps.find((s) => s.key === key);
              const action = actionForItem(item, { canManageSlots });
              const overdue = step?.state === "overdue";
              return (
                <article
                  key={pairKey(item)}
                  className={cn(
                    "flex flex-col gap-1.5 rounded-lg border bg-card p-3",
                    overdue || hot ? "border-destructive/40" : "border-border",
                  )}
                  data-testid="cycle-board-card"
                >
                  <button
                    type="button"
                    onClick={() => onSelect(pairKey(item))}
                    className="text-left"
                  >
                    <div className="text-sm font-semibold text-foreground">{candidateLabel(item)}</div>
                    <div className="text-xs text-muted-foreground">{pairContext(item)}</div>
                  </button>
                  {step?.at || step?.meta ? (
                    <div
                      className={cn(
                        "text-xs font-semibold tabular-nums",
                        step?.at && "font-mono",
                        overdue || hot ? "text-destructive" : "text-foreground/80",
                      )}
                    >
                      {step?.at
                        ? `${key === "call" ? "do " : ""}${formatDayLabel(step.at)} ${formatTime(step.at)}`
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
            })}
          </section>
        );
      })}
    </div>
  );
}
