"use client";

import { StatusDot } from "@/components/ds";
import type { LawChangeListItem } from "@/lib/api/compliance";

import {
  ROLE_LABEL,
  daysLeftLabel,
  daysLeftTone,
  deadlineEntries,
  deadlinesByMonth,
  monthTitle,
} from "./compliance-model";

interface DeadlinesViewProps {
  changes: LawChangeListItem[];
  today: string;
  onOpen: (id: number) => void;
}

/** „Terminy”: daty otwartych zmian, miesiące jako kolumny. */
export function DeadlinesView({ changes, today, onOpen }: DeadlinesViewProps) {
  const months = deadlinesByMonth(deadlineEntries(changes, today));
  if (!months.length) {
    return (
      <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        Brak terminów w otwartych zmianach dla tej roli.
      </div>
    );
  }
  return (
    <div className="grid min-w-0 gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {months.map(({ month, entries }) => (
        <section key={month} className="min-w-0 self-start rounded-lg border border-border bg-card">
          <h2 className="border-b border-border/70 px-3.5 py-2 text-[13px] font-semibold">{monthTitle(month)}</h2>
          <ul className="divide-y divide-border/60">
            {entries.map((entry) => (
              <li key={entry.key}>
                <button
                  type="button"
                  onClick={() => onOpen(entry.changeId)}
                  className="grid w-full gap-0.5 px-3.5 py-2 text-left transition-colors hover:bg-muted/40"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-display text-sm font-semibold tabular-nums">
                      {Number(entry.date.slice(8, 10))}
                    </span>
                    <StatusDot tone={daysLeftTone(entry.days)}>{daysLeftLabel(entry.days)}</StatusDot>
                  </div>
                  <span className="text-[13px] leading-5">{entry.title}</span>
                  <span className="text-[11px] text-muted-foreground">
                    {entry.kind === "deadline" ? "Termin dla nas" : "Wejście w życie"}
                    {entry.roles.length ? ` · ${entry.roles.map((role) => ROLE_LABEL[role] ?? role).join(", ")}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
