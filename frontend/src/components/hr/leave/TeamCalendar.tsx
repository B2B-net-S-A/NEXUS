"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { HrConfig } from "@/lib/api/hr";
import {
  useTeamCalendar,
  type CalendarAbsence,
  type CalendarPresenceKind,
  type TeamCalendar as TeamCalendarData,
  type TeamCalendarPerson,
} from "@/lib/api/hr-leave";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { WEEKDAYS_PL, monthTitlePl, shiftMonth } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

import { personInitials } from "../people/hr-format";
import {
  HALF_DAY_LABELS,
  PRESENCE_LABELS,
  calendarCells,
  formatRange,
  matchesStatusFilter,
  presenceByDay,
  shortName,
  type CalendarStatusFilter,
} from "./leave-format";

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
  const [status, setStatus] = useState<CalendarStatusFilter>("all");
  const [selected, setSelected] = useState<Selected | null>(null);
  const calendar = useTeamCalendar(
    month,
    filter.kind === "department" ? filter.name : null,
    filter.kind === "team",
  );
  const data = calendar.data;
  const people = useMemo(
    () =>
      (data?.people ?? []).filter((person) =>
        matchesStatusFilter(person, status, data?.today ?? today, month),
      ),
    [data, status, today, month],
  );
  const statusCounts = useMemo(() => {
    const all = data?.people ?? [];
    const on = data?.today ?? today;
    return {
      absent: all.filter((person) => matchesStatusFilter(person, "absent", on, month)).length,
      remote: all.filter((person) => matchesStatusFilter(person, "remote", on, month)).length,
    };
  }, [data, today, month]);
  const todayInView = (data?.today ?? today).startsWith(month);
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
        <b className="min-w-[132px] text-center text-sm text-foreground">{monthTitlePl(month)}</b>
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
        <Select
          value={status}
          onValueChange={(value) => {
            setStatus(value as CalendarStatusFilter);
            setSelected(null);
          }}
        >
          <SelectTrigger className="h-8 w-[220px]" aria-label="Kto">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Wszyscy</SelectItem>
            <SelectItem value="absent">
              {`Nieobecni${todayInView ? " dziś" : ""} (${statusCounts.absent})`}
            </SelectItem>
            {data?.presence_shown ? (
              <SelectItem value="remote">
                {`Zdalnie${todayInView ? " dziś" : ""} (${statusCounts.remote})`}
              </SelectItem>
            ) : null}
          </SelectContent>
        </Select>
        <Legend withPresence={Boolean(data?.presence_shown)} />
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
      ) : people.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          {status === "remote"
            ? `Nikt nie pracuje zdalnie${todayInView ? " dziś" : " w tym miesiącu"}.`
            : `Nikt nie jest nieobecny${todayInView ? " dziś" : " w tym miesiącu"}.`}
        </p>
      ) : (
        <>
          <CalendarGrid
            data={data}
            people={people}
            selected={selected}
            onSelect={setSelected}
          />
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
function Legend({ withPresence }: { withPresence: boolean }) {
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
      {withPresence ? (
        <>
          <span className="inline-flex items-center gap-1.5">
            <PresenceMark kind="remote" />
            {PRESENCE_LABELS.remote}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <PresenceMark kind="business_trip" />
            {PRESENCE_LABELS.business_trip}
          </span>
        </>
      ) : null}
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-4 rounded-sm bg-muted" />
        wolne
      </span>
    </div>
  );
}

/** Znacznik pracy zdalnej („Z”) albo delegacji („D”) — wyjątek obecności, nie nieobecność. */
function PresenceMark({ kind }: { kind: CalendarPresenceKind }) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid h-3 w-4 place-items-center rounded-sm text-[8.5px] font-semibold leading-none",
        kind === "remote"
          ? "bg-info-muted text-info-muted-foreground"
          : "bg-warning-muted text-warning-muted-foreground",
      )}
    >
      {kind === "remote" ? "Z" : "D"}
    </span>
  );
}

interface CalendarGridProps {
  data: TeamCalendarData;
  /** Osoby po filtrze „wszyscy / nieobecni / zdalnie”. */
  people: TeamCalendarPerson[];
  selected: Selected | null;
  onSelect: (selected: Selected | null) => void;
}

function CalendarGrid({ data, people, selected, onSelect }: CalendarGridProps) {
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
                  <span className="block text-[9.5px]">{WEEKDAYS_PL[day.weekday]}</span>
                  <span className={cn("block tabular-nums", isToday && "font-semibold")}>
                    {Number(day.date.slice(8, 10))}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {people.map((person) => {
            const cells = calendarCells(person.absences, days);
            const presence = presenceByDay(person.presence);
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
                    const mark = presence.get(day.date);
                    return (
                      <td
                        key={day.date}
                        className={cn("p-0", off && "bg-muted", isToday && "bg-primary/5")}
                      >
                        {mark ? (
                          <span
                            role="img"
                            aria-label={`${person.name}: ${PRESENCE_LABELS[mark]} ${formatRange(day.date, day.date)}`}
                            title={PRESENCE_LABELS[mark]}
                            className={cn(
                              "mx-auto grid h-6 w-full place-items-center rounded-sm text-[10px] font-semibold",
                              mark === "remote"
                                ? "bg-info-muted text-info-muted-foreground"
                                : "bg-warning-muted text-warning-muted-foreground",
                            )}
                          >
                            {mark === "remote" ? "Z" : "D"}
                          </span>
                        ) : null}
                      </td>
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
