"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import type { HrConfig } from "@/lib/api/hr";
import {
  useTeamCalendar,
  type CalendarAbsence,
  type TeamCalendar as TeamCalendarData,
  type TeamCalendarPerson,
} from "@/lib/api/hr-leave";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { personInitials } from "../people/hr-format";
import {
  HALF_DAY_LABELS,
  calendarCells,
  formatRange,
  monthLabel,
  shiftMonth,
  shortName,
  warsawToday,
} from "./leave-format";

const WEEKDAY_SHORT = ["pn", "wt", "śr", "cz", "pt", "sb", "nd"];

type Filter = { kind: "all" } | { kind: "team" } | { kind: "department"; name: string };

interface Selected {
  person: TeamCalendarPerson;
  absence: CalendarAbsence;
}

function chipClass(active: boolean): string {
  return cn(
    "inline-flex h-8 items-center rounded-full border px-3 text-xs transition-colors",
    active
      ? "border-primary bg-primary/10 text-primary"
      : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
  );
}

/** „Ludzie → Kalendarz zespołu”: osoby × dni miesiąca, nieobecność jako pasek. */
export function TeamCalendar({ config }: { config: HrConfig }) {
  const today = warsawToday();
  const [month, setMonth] = useState(today.slice(0, 7));
  const [filter, setFilter] = useState<Filter>({ kind: "all" });
  const [selected, setSelected] = useState<Selected | null>(null);
  const calendar = useTeamCalendar(
    month,
    filter.kind === "department" ? filter.name : null,
    filter.kind === "team",
  );
  const data = calendar.data;
  const state = resolveViewState({
    isLoading: calendar.isLoading,
    isError: calendar.isError,
    error: calendar.error,
    isSuccess: calendar.isSuccess,
    isEmpty: (data?.people.length ?? 0) === 0,
  });

  const go = (next: string) => {
    setMonth(next);
    setSelected(null);
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="ghost"
          aria-label="Poprzedni miesiąc"
          onClick={() => go(shiftMonth(month, -1))}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden />
        </Button>
        <b className="min-w-[132px] text-center text-sm text-foreground">{monthLabel(month)}</b>
        <Button
          size="sm"
          variant="ghost"
          aria-label="Następny miesiąc"
          onClick={() => go(shiftMonth(month, 1))}
        >
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Button>
        {month !== today.slice(0, 7) ? (
          <Button size="sm" variant="quiet" onClick={() => go(today.slice(0, 7))}>
            Ten miesiąc
          </Button>
        ) : null}
        <div className="flex flex-wrap items-center gap-1.5 md:ml-3">
          <button
            type="button"
            className={chipClass(filter.kind === "all")}
            onClick={() => setFilter({ kind: "all" })}
          >
            Wszyscy
          </button>
          {config.me.is_manager ? (
            <button
              type="button"
              className={chipClass(filter.kind === "team")}
              onClick={() => setFilter({ kind: "team" })}
            >
              Mój zespół
            </button>
          ) : null}
          {(data?.departments ?? []).map((name) => (
            <button
              key={name}
              type="button"
              className={chipClass(filter.kind === "department" && filter.name === name)}
              onClick={() => setFilter({ kind: "department", name })}
            >
              {name}
            </button>
          ))}
        </div>
        <Legend />
      </div>

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie kalendarza…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={
            state === "forbidden"
              ? "Kalendarz zespołu widzą osoby z kartoteką pracownika i Kadry."
              : state === "not_found"
                ? "Moduł urlopów nie jest jeszcze włączony."
                : undefined
          }
          onRetry={() => calendar.refetch()}
        />
      ) : state === "empty" || !data ? (
        <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Nikt z tego zakresu nie ma kartoteki w tym miesiącu.
        </p>
      ) : (
        <>
          <CalendarGrid data={data} selected={selected} onSelect={setSelected} />
          {selected ? <SelectedAbsence selected={selected} /> : null}
        </>
      )}
    </div>
  );
}

/**
 * Legenda: „nieobecność” to zatwierdzony urlop (UoP) albo zgłoszona przerwa
 * (B2B, zlecenie — D5, bez akceptacji); „czeka na akceptację” zdarza się
 * tylko przy umowie o pracę.
 */
function Legend() {
  return (
    <div className="ml-auto flex flex-wrap items-center gap-3 text-[11.5px] text-muted-foreground">
      <span
        className="inline-flex items-center gap-1.5"
        title="Zatwierdzony urlop albo zgłoszona przerwa (B2B, zlecenie)"
      >
        <span aria-hidden className="h-3 w-4 rounded-sm bg-primary/25" />
        nieobecność · przerwa
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-4 rounded-sm border border-dashed border-primary/60" />
        wniosek czeka na akceptację
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-4 rounded-sm bg-muted" />
        wolne
      </span>
    </div>
  );
}

interface CalendarGridProps {
  data: TeamCalendarData;
  selected: Selected | null;
  onSelect: (selected: Selected | null) => void;
}

function CalendarGrid({ data, selected, onSelect }: CalendarGridProps) {
  const days = useMemo(() => data.days.map((day) => day.date), [data.days]);
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full min-w-[720px] table-fixed border-collapse text-xs">
        <colgroup>
          <col className="w-[168px]" />
          {data.days.map((day) => (
            <col key={day.date} />
          ))}
        </colgroup>
        <thead>
          <tr className="border-b border-border/60">
            <th className="sticky left-0 z-10 bg-card px-3 py-1.5 text-left text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
              Osoba
            </th>
            {data.days.map((day) => {
              const off = day.kind !== "work";
              const isToday = day.date === data.today;
              return (
                <th
                  key={day.date}
                  title={day.name ?? undefined}
                  className={cn(
                    "px-0 py-1 text-center font-normal leading-tight",
                    off ? "bg-muted text-muted-foreground/70" : "text-muted-foreground",
                    isToday && "text-primary",
                  )}
                >
                  <span className="block text-[9.5px]">{WEEKDAY_SHORT[day.weekday]}</span>
                  <span className={cn("block tabular-nums", isToday && "font-semibold")}>
                    {Number(day.date.slice(8, 10))}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {data.people.map((person) => {
            const cells = calendarCells(person.absences, days);
            return (
              <tr key={person.user_id} className="h-9 border-b border-border/60 last:border-b-0">
                <th
                  scope="row"
                  className="sticky left-0 z-10 bg-card px-3 text-left font-normal"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden
                      className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
                    >
                      {personInitials(person.name)}
                    </span>
                    <span className={cn("truncate text-foreground", person.is_me && "font-semibold")}>
                      {person.name}
                    </span>
                  </span>
                </th>
                {data.days.map((day) => {
                  const cell = cells.get(day.date);
                  const off = day.kind !== "work";
                  const isToday = day.date === data.today;
                  if (!cell || cell.kind === "none") {
                    return (
                      <td
                        key={day.date}
                        className={cn("p-0", off && "bg-muted", isToday && "bg-primary/5")}
                      />
                    );
                  }
                  const active =
                    selected?.person.user_id === person.user_id &&
                    selected.absence === cell.absence;
                  return (
                    <td key={day.date} className={cn("p-0.5", off && "bg-muted")}>
                      <button
                        type="button"
                        aria-label={`${person.name}: ${cell.absence.label} ${formatRange(cell.absence.start_date, cell.absence.end_date)}`}
                        onClick={() =>
                          onSelect(active ? null : { person, absence: cell.absence })
                        }
                        className={cn(
                          "block h-6 rounded-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          cell.half ? "w-1/2" : "w-full",
                          cell.kind === "absent"
                            ? off
                              ? "bg-primary/10"
                              : "bg-primary/25 hover:bg-primary/35"
                            : "border border-dashed border-primary/60 hover:bg-primary/10",
                          active && "ring-2 ring-primary",
                        )}
                      />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SelectedAbsence({ selected }: { selected: Selected }) {
  const { person, absence } = selected;
  return (
    <div className="rounded-lg border border-border bg-card p-4 text-sm" aria-live="polite">
      <p className="font-medium text-foreground">
        {person.name} · {absence.label}
        {absence.status === "pending" ? " (czeka na akceptację)" : ""}
      </p>
      <p className="text-muted-foreground">
        {formatRange(absence.start_date, absence.end_date)}
        {absence.half_day ? `, ${HALF_DAY_LABELS[absence.half_day]}` : ""}
        {absence.substitute_name
          ? ` · zastępuje ${shortName(absence.substitute_name)}`
          : " · bez zastępcy"}
      </p>
      {!person.type_visible ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Rodzaj nieobecności widzą tylko ta osoba, jej przełożony albo koordynator i Kadry.
        </p>
      ) : null}
    </div>
  );
}
