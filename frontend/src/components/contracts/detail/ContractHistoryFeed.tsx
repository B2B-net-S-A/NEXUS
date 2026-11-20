"use client";
// Zakładka „Historia” kontraktu (przebudowa 19.11.2026, wariant A): zdarzenia
// po miesiącach, jedno zdanie na zdarzenie, automatyczne wyszarzone, serie
// zwinięte, pigułki filtrów z licznikami. Treść liczy `lib/contract-history.ts`.
import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  groupHistory,
  groupTitle,
  HISTORY_FILTERS,
  humanizeActivity,
  type ContractActivity,
  type HistoryEvent,
  type HistoryKind,
} from "@/lib/contract-history";

const MONTHS = [
  "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
  "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
];

function dayMonth(iso: string): string {
  const [, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}`;
}

function EventLine({ e, title, count }: { e: HistoryEvent; title: string; count?: number }) {
  return (
    <span className="flex min-w-0 flex-1 items-baseline gap-2">
      <span
        className={cn("shrink-0 font-medium", e.automatic ? "text-muted-foreground" : "text-foreground")}
        data-testid={`contract-activity-${e.id}-label`}
      >
        {title}
      </span>
      {e.detail && !count ? (
        <span className="min-w-0 truncate text-muted-foreground" title={e.detail} data-testid={`contract-activity-${e.id}-details`}>
          · {e.detail}
        </span>
      ) : null}
    </span>
  );
}

export function ContractHistoryFeed({ activities }: { activities: ContractActivity[] }) {
  const [filter, setFilter] = useState<"all" | HistoryKind>("all");
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const events = useMemo(() => activities.map(humanizeActivity), [activities]);
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: events.length };
    for (const e of events) c[e.kind] = (c[e.kind] ?? 0) + 1;
    return c;
  }, [events]);
  const visible = filter === "all" ? events : events.filter((e) => e.kind === filter);
  const byMonth = new Map<string, HistoryEvent[]>();
  for (const e of visible) {
    const key = e.at.slice(0, 7);
    byMonth.set(key, [...(byMonth.get(key) ?? []), e]);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="tablist" aria-label="Rodzaj zdarzeń" className="flex flex-wrap gap-1.5">
          {HISTORY_FILTERS.map((f) => {
            const active = filter === f.key;
            const n = counts[f.key] ?? 0;
            return (
              <button
                key={f.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setFilter(f.key)}
                disabled={n === 0 && f.key !== "all"}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] font-medium disabled:opacity-50",
                  active ? "border-primary/40 bg-primary/8 text-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground",
                )}
              >
                {f.label}
                <span className={cn("rounded-full px-1.5 text-[11px] tabular-nums", active ? "bg-primary text-primary-foreground" : "bg-muted")}>{n}</span>
              </button>
            );
          })}
        </div>
        <p className="text-[12px] text-muted-foreground">Zdarzenia automatyczne są wyszarzone</p>
      </div>

      <div className="rounded-xl border border-border bg-card px-4 py-2 shadow-xs">
        {[...byMonth.entries()].map(([month, monthEvents]) => {
          const [y, m] = month.split("-");
          return (
            <section key={month} aria-label={`${MONTHS[Number(m) - 1]} ${y}`} className="py-1.5">
              <h3 className="flex items-center gap-2 py-1.5 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                {MONTHS[Number(m) - 1]} {y}
                <span aria-hidden className="h-px flex-1 bg-border/70" />
              </h3>
              <ol>
                {groupHistory(monthEvents).map((g) => {
                  const e = g.events[0];
                  const many = g.events.length > 1;
                  const expanded = open[g.key];
                  return (
                    <li key={g.key} className="border-b border-border/50 last:border-b-0">
                      <div className="flex items-center gap-3 py-1.5 text-[13px]">
                        <span className="w-11 shrink-0 tabular-nums text-muted-foreground">{dayMonth(e.at)}</span>
                        <EventLine e={e} title={groupTitle(g)} count={many ? g.events.length : undefined} />
                        <span className={cn("shrink-0 text-[12.5px]", e.automatic ? "text-muted-foreground/80" : "text-foreground")}>
                          {e.automatic ? "automatycznie" : (e.who ?? "NEXUS")}
                        </span>
                        {many ? (
                          <button
                            type="button"
                            onClick={() => setOpen((s) => ({ ...s, [g.key]: !s[g.key] }))}
                            aria-expanded={Boolean(expanded)}
                            aria-label={expanded ? "Zwiń" : "Pokaż wszystkie"}
                            className="hit-area rounded p-0.5 text-muted-foreground hover:bg-muted"
                          >
                            {expanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                          </button>
                        ) : (
                          <span className="w-5 shrink-0" />
                        )}
                      </div>
                      {many && expanded ? (
                        <ul className="pb-2 pl-14 text-[12.5px] text-muted-foreground">
                          {g.events.map((x) => (
                            <li key={x.id} className="truncate">
                              {x.title}
                              {x.detail ? ` · ${x.detail}` : ""}
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  );
                })}
              </ol>
            </section>
          );
        })}
        {visible.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">Brak zdarzeń tego rodzaju.</p> : null}
      </div>
    </div>
  );
}
