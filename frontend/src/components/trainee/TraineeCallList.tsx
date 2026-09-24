"use client";

import { Clock } from "lucide-react";

import type { TraineeItem } from "@/lib/api/trainee";
import { OUTCOME_LABEL, missingLabel, retryLabel } from "@/lib/trainee-call";
import { cn } from "@/lib/utils";

export type TraineeListTab = "open" | "closed";

interface TraineeCallListProps {
  tab: TraineeListTab;
  onTabChange: (tab: TraineeListTab) => void;
  open: TraineeItem[];
  closed: TraineeItem[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "min-h-10 flex-1 rounded-md px-3 text-sm transition-colors pointer-coarse:min-h-11",
        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-card font-semibold text-foreground shadow-xs"
          : "font-medium text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

/** Lewa kolumna: „Do zrobienia” / „Zamknięte”, jedna osoba = jeden przycisk. */
export function TraineeCallList({
  tab,
  onTabChange,
  open,
  closed,
  selectedId,
  onSelect,
}: TraineeCallListProps) {
  const rows = tab === "open" ? open : closed;
  return (
    <section
      aria-label="Lista na dziś"
      className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-card"
    >
      <div className="flex gap-1 border-b border-border bg-muted p-1">
        <TabButton active={tab === "open"} onClick={() => onTabChange("open")}>
          Do zrobienia · {open.length}
        </TabButton>
        <TabButton active={tab === "closed"} onClick={() => onTabChange("closed")}>
          Zamknięte · {closed.length}
        </TabButton>
      </div>
      <p className="px-4 pt-3 text-xs text-muted-foreground">
        {tab === "open"
          ? "Najpierw osoby pasujące do otwartych rekrutacji. Kto nie odebrał, wraca na koniec listy."
          : "Pozycje z wynikiem. Po rozmowie możesz jeszcze przekazać osobę rekruterowi."}
      </p>
      {rows.length === 0 ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          {tab === "open" ? "Nikt nie czeka na telefon." : "Nie zamknięto jeszcze żadnej pozycji."}
        </p>
      ) : (
        <ul className="flex flex-col gap-2 overflow-y-auto p-3 lg:max-h-[calc(100dvh-19rem)]">
          {rows.map((item) => {
            const current = item.id === selectedId;
            const retry = retryLabel(item);
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onSelect(item.id)}
                  aria-current={current ? "true" : undefined}
                  className={cn(
                    "flex w-full flex-col gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors",
                    "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                    current
                      ? "border-primary bg-primary/5 ring-1 ring-inset ring-primary"
                      : "border-border bg-card hover:bg-muted",
                  )}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-semibold text-foreground">
                      {item.name}
                    </span>
                    {item.city ? (
                      <span className="shrink-0 text-xs text-muted-foreground">{item.city}</span>
                    ) : null}
                  </span>
                  {item.role ? (
                    <span className="truncate text-xs text-muted-foreground">{item.role}</span>
                  ) : null}
                  {tab === "closed" && item.outcome ? (
                    <span className="text-xs font-medium text-foreground">
                      {OUTCOME_LABEL[item.outcome] ?? item.outcome}
                    </span>
                  ) : (
                    <span className="flex flex-wrap gap-1">
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">
                        pasuje do {item.reasons.fits} rekrutacji
                      </span>
                      {item.reasons.missing.map((code) => (
                        <span
                          key={code}
                          className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
                        >
                          {missingLabel(code)}
                        </span>
                      ))}
                    </span>
                  )}
                  {retry ? (
                    <span className="flex items-center gap-1 text-[11px] font-medium text-warning-muted-foreground">
                      <Clock className="h-3 w-3 shrink-0" aria-hidden />
                      {retry}
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
