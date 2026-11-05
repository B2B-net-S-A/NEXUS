"use client";

import { useInterviewCycle } from "@/lib/api/interviewCycle";
import { AGENDA_LABELS, type AgendaEntry } from "@/lib/interview-cycle";

import { shortName } from "./access";
import { Block, Kpi, Loaded, Rows, count, hhmm } from "./ui";

const warsawDay = (at: string | Date) => new Date(at).toLocaleDateString("sv-SE", { timeZone: "Europe/Warsaw" });

/** Wpisy planu z dzisiejszego dnia, od najwcześniejszego. */
export function todayAgenda(agenda: readonly AgendaEntry[], now: Date = new Date()): AgendaEntry[] {
  const today = warsawDay(now);
  return agenda
    .filter((a) => warsawDay(a.start) === today)
    .sort((a, b) => a.start.localeCompare(b.start));
}

/** Plan dnia: imię i litera nazwiska (decyzja Artura 05.11.2026), bez telefonów i maili. */
export function TodaySection({ whole }: { whole: boolean }) {
  const cycle = useInterviewCycle(whole ? "all" : "mine");
  return (
    <div className="pb-2">
      <Loaded query={cycle} height="h-64">
        {(d) => {
          const rows = todayAgenda(d.agenda);
          const interviews = rows.filter((r) => r.kind === "interview").length;
          return (
            <>
              <div className="grid grid-cols-2 gap-2 px-4 pt-4">
                <Kpi label="Rozmowy u klienta" value={count(interviews)} />
                <Kpi label="Prepy i telefony" value={count(rows.length - interviews)} />
              </div>
              <Block title="Plan dnia" note={whole ? "cały zespół" : "moje"}>
                {rows.length === 0 ? (
                  <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Dziś nic nie jest zaplanowane.</p>
                ) : (
                  <Rows>
                    {rows.map((a) => (
                      <div key={`${a.kind}-${a.event_id ?? a.slot_request_id}-${a.start}`} className="flex gap-3 px-3 py-2.5 text-sm">
                        <b className="w-11 shrink-0 tabular-nums">{hhmm(a.start)}</b>
                        <div className="min-w-0">
                          <div className="truncate font-medium">{shortName(a.candidate_name)}</div>
                          <div className="truncate text-xs text-muted-foreground">{AGENDA_LABELS[a.kind]} · {a.client_name}</div>
                        </div>
                      </div>
                    ))}
                  </Rows>
                )}
              </Block>
            </>
          );
        }}
      </Loaded>
    </div>
  );
}
