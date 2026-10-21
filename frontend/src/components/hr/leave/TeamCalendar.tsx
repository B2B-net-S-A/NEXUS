"use client";

import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";

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
import { WEEKDAYS_PL, formatWeekdayDayPl } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

import { personInitials } from "../people/hr-format";
import {
  absenceSegments,
  absentCounts,
  addDays,
  calendarWindow,
  hardestDay,
  heatLevel,
  matchesName,
  mergeCalendars,
  mondayOf,
  presenceMarks,
  shiftAnchor,
  weekAbsentees,
  windowTitle,
  type AbsentCount,
  type CalendarView,
} from "./calendar-bars";
import {
  HALF_DAY_LABELS,
  PRESENCE_LABELS,
  formatRange,
  matchesStatusFilter,
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

/** Szerokość kolumny osoby i dni (siatka CSS — paski przez kilka dni). */
function gridStyle(days: number): CSSProperties {
  return { gridTemplateColumns: `170px repeat(${days}, minmax(0, 1fr))` };
}

/**
 * „Ludzie → Kalendarz zespołu” (makieta 19.10.2026): ciągłe paski
 * nieobecności z etykietą, wiersz „Nieobecnych” (mapa cieplna), mocna
 * kolumna „dziś”, „Znajdź osobę”, widok 2 tygodnie / miesiąc i panel
 * „W tym tygodniu nie ma”. Rodzaj tylko z serwera (D6).
 */
export function TeamCalendar({ config }: { config: HrConfig }) {
  const today = warsawToday();
  const [view, setView] = useState<CalendarView>("month");
  const [anchor, setAnchor] = useState(`${today.slice(0, 7)}-01`);
  const [filter, setFilter] = useState<Filter>({ kind: "all" });
  const [status, setStatus] = useState<CalendarStatusFilter>("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Selected | null>(null);
  const frame = calendarWindow(view, anchor);
  const department = filter.kind === "department" ? filter.name : null;
  const team = filter.kind === "team";
  const first = useTeamCalendar(frame.months[0], department, team);
  const second = useTeamCalendar(frame.months[1] ?? frame.months[0], department, team);
  const parts = frame.months.length > 1 ? [first, second] : [first];
  const loaded = parts.every((part) => part.isSuccess && part.data);
  // Dwa miesiące naraz tylko w widoku 2 tygodni na przełomie miesiąca.
  const data = loaded
    ? mergeCalendars(
        parts.map((part) => part.data as TeamCalendarData),
        frame,
      )
    : null;
  const failed = parts.find((part) => part.isError);
  const serverToday = data?.today ?? today;
  const todayInView = serverToday >= frame.start && serverToday <= frame.end;
  // Filtr „Kto”: stan na dziś, gdy dziś jest w oknie; inaczej ktokolwiek w okresie.
  const statusMonth = todayInView ? serverToday.slice(0, 7) : "-";
  const people = (data?.people ?? []).filter(
    (person) =>
      matchesName(person, query) &&
      matchesStatusFilter(person, status, serverToday, statusMonth),
  );
  const statusCounts = {
    absent: (data?.people ?? []).filter((person) =>
      matchesStatusFilter(person, "absent", serverToday, statusMonth),
    ).length,
    remote: (data?.people ?? []).filter((person) =>
      matchesStatusFilter(person, "remote", serverToday, statusMonth),
    ).length,
  };
  const state = resolveViewState({
    isLoading: parts.some((part) => part.isLoading),
    isError: Boolean(failed),
    error: failed?.error ?? null,
    isSuccess: loaded,
    isEmpty: (data?.people.length ?? 0) === 0,
  });

  const go = (next: string) => {
    setAnchor(next);
    setSelected(null);
  };
  const switchView = (next: CalendarView) => {
    if (next === view) return;
    setView(next);
    setSelected(null);
    // Tydzień dziś, gdy dziś w oglądanym miesiącu; inaczej początek miesiąca.
    if (next === "two_weeks") setAnchor(todayInView ? serverToday : frame.start);
    else setAnchor(`${anchor.slice(0, 7)}-01`);
  };
  const atToday = view === "month" ? anchor.slice(0, 7) === today.slice(0, 7) : todayInView;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2" data-help="hr.team_calendar.filters">
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="outline"
            aria-label={view === "month" ? "Poprzedni miesiąc" : "Poprzednie dwa tygodnie"}
            onClick={() => go(shiftAnchor(view, anchor, -1))}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </Button>
          <b className="min-w-[150px] px-1 text-center text-sm text-foreground">
            {windowTitle(view, frame)}
          </b>
          <Button
            size="sm"
            variant="outline"
            aria-label={view === "month" ? "Następny miesiąc" : "Następne dwa tygodnie"}
            onClick={() => go(shiftAnchor(view, anchor, 1))}
          >
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
          {atToday ? null : (
            <Button
              size="sm"
              variant="outline"
              onClick={() => go(view === "month" ? `${today.slice(0, 7)}-01` : today)}
            >
              Dziś
            </Button>
          )}
        </div>
        <div
          role="group"
          aria-label="Zakres kalendarza"
          className="inline-flex rounded-lg border border-border bg-card p-0.5"
        >
          {(
            [
              ["two_weeks", "2 tygodnie"],
              ["month", "Miesiąc"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={view === value}
              onClick={() => switchView(value)}
              className={cn(
                "h-7 rounded-md px-3 text-xs font-medium transition-colors",
                view === value
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
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
          <SelectTrigger className="h-8 w-[200px]" aria-label="Kto">
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
        <label className="flex h-8 w-full items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 sm:ml-auto sm:w-[200px]">
          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Znajdź osobę"
            aria-label="Znajdź osobę w kalendarzu"
            className="w-0 min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
        </label>
      </div>

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie kalendarza…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={
            state === "forbidden"
              ? "Kalendarz zespołu widzą osoby z kartoteką w NEXUSIE i Kadry."
              : state === "not_found"
                ? "Moduł urlopów nie jest jeszcze włączony."
                : undefined
          }
          onRetry={() => parts.forEach((part) => void part.refetch())}
        />
      ) : state === "empty" || !data ? (
        <p className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Nikt z tego zakresu nie ma kartoteki w tym okresie.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-start gap-4">
            <div className="min-w-0 flex-[999_1_760px] overflow-hidden rounded-xl border border-border bg-card">
              {people.length === 0 ? (
                <p className="p-8 text-center text-sm text-muted-foreground">
                  {query.trim()
                    ? `Nikt nie pasuje do „${query.trim()}”.`
                    : status === "remote"
                      ? `Nikt nie pracuje zdalnie${todayInView ? " dziś" : " w tym okresie"}.`
                      : `Nikt nie jest nieobecny${todayInView ? " dziś" : " w tym okresie"}.`}
                </p>
              ) : (
                <CalendarGrid
                  data={data}
                  people={people}
                  view={view}
                  selected={selected}
                  onSelect={setSelected}
                />
              )}
              <Legend withPresence={Boolean(data.presence_shown)} />
            </div>
            <SidePanel data={data} people={people} today={serverToday} todayInView={todayInView} />
          </div>
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
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border/60 px-3 py-2.5 text-xs text-muted-foreground"
      data-help="hr.team_calendar.legend"
    >
      <span
        className="inline-flex items-center gap-1.5"
        title="Zatwierdzony urlop albo zgłoszona przerwa (B2B, zlecenie)"
      >
        <span aria-hidden className="h-2.5 w-3.5 rounded-sm bg-primary/25" />
        nieobecność · przerwa
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-2.5 w-3.5 rounded-sm border border-dashed border-primary/60" />
        wniosek czeka na akceptację
      </span>
      {withPresence ? (
        <>
          <span className="inline-flex items-center gap-1.5">
            <PresenceMark kind="remote" />Z · {PRESENCE_LABELS.remote}
          </span>
          <span className="inline-flex items-center gap-1.5">
            <PresenceMark kind="business_trip" />W · {PRESENCE_LABELS.business_trip}
          </span>
        </>
      ) : null}
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden className="h-2.5 w-3.5 rounded-sm bg-muted" />
        wolne
      </span>
      <span>„?” w wierszu „Nieobecnych” = z wnioskiem, który czeka · ½ = pół dnia</span>
    </div>
  );
}

/** Znacznik pracy zdalnej („Z”) albo delegacji („D”) — wyjątek obecności, nie nieobecność. */
function PresenceMark({ kind }: { kind: CalendarPresenceKind }) {
  return (
    <span
      aria-hidden
      className={cn(
        "h-2.5 w-3.5 rounded-sm",
        kind === "remote" ? "bg-info-muted" : "bg-warning-muted",
      )}
    />
  );
}

const HEAT: Record<ReturnType<typeof heatLevel>, string> = {
  low: "bg-primary/10 text-primary",
  mid: "bg-primary/25 text-primary",
  high: "bg-primary/60 text-primary-foreground",
};

interface CalendarGridProps {
  data: TeamCalendarData;
  /** Osoby po filtrze „wszyscy / nieobecni / zdalnie” i po szukaniu. */
  people: TeamCalendarPerson[];
  view: CalendarView;
  selected: Selected | null;
  onSelect: (selected: Selected | null) => void;
}

function CalendarGrid({ data, people, view, selected, onSelect }: CalendarGridProps) {
  const days = useMemo(() => data.days.map((day) => day.date), [data.days]);
  const counts = useMemo(() => absentCounts(people, data.days), [people, data.days]);
  const style = gridStyle(data.days.length);
  const offOrToday = data.days
    .map((day, index) => ({ day, index }))
    .filter(({ day }) => day.kind !== "work" || day.date === data.today);

  /** Tło kolumn: dni wolne szare, dziś z obwódką — w każdym wierszu ta sama siatka. */
  const background = offOrToday.map(({ day, index }) => (
    <div
      key={`bg-${day.date}`}
      aria-hidden
      style={{ gridColumn: index + 2, gridRow: 1 }}
      className={cn(
        "h-full",
        day.date === data.today ? "border-x-2 border-primary bg-primary/10" : "bg-muted/60",
      )}
    />
  ));

  return (
    <div className="overflow-x-auto" data-help="hr.team_calendar.grid">
      <div
        role="table"
        aria-label="Nieobecności zespołu"
        className={cn("text-xs", view === "month" ? "min-w-[900px]" : "min-w-[640px]")}
      >
        <div role="rowgroup">
          <div role="row" className="grid border-b border-border" style={style}>
            <div
              role="columnheader"
              className="sticky left-0 z-20 bg-card px-3 py-1.5 text-left text-[10.5px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
            >
              Osoba
            </div>
            {data.days.map((day) => {
              const isToday = day.date === data.today;
              return (
                <div
                  key={day.date}
                  role="columnheader"
                  title={day.name ?? undefined}
                  className={cn(
                    "py-1.5 text-center leading-tight",
                    day.kind !== "work" ? "bg-muted/60 text-muted-foreground/70" : "text-muted-foreground",
                    isToday && "border-x-2 border-t-2 border-primary bg-primary/10 text-primary",
                  )}
                >
                  <span className="block text-[10px]">{WEEKDAYS_PL[day.weekday]}</span>
                  <span
                    className={cn(
                      "block text-xs font-semibold tabular-nums",
                      isToday ? "text-primary" : "text-foreground",
                    )}
                  >
                    {Number(day.date.slice(8, 10))}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        <div role="rowgroup">
          {people.map((person) => {
            const segments = absenceSegments(person.absences, days);
            const marks = presenceMarks(person, days, segments);
            return (
              <div
                key={person.user_id}
                role="row"
                className="grid h-[38px] items-center border-b border-border/60"
                style={{ ...style, gridTemplateRows: "38px" }}
              >
                <div
                  role="rowheader"
                  style={{ gridColumn: 1, gridRow: 1 }}
                  className="sticky left-0 z-20 flex h-full min-w-0 items-center gap-2 bg-card px-3"
                >
                  <span
                    aria-hidden
                    className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
                  >
                    {personInitials(person.name)}
                  </span>
                  <span
                    className={cn(
                      "truncate text-[13px] text-foreground",
                      person.is_me && "font-semibold",
                    )}
                  >
                    {person.name}
                  </span>
                </div>
                {background}
                {segments.map((segment) => {
                  const active =
                    selected?.person.user_id === person.user_id &&
                    selected.absence === segment.absence;
                  const range = formatRange(segment.absence.start_date, segment.absence.end_date);
                  return (
                    <div
                      key={`${segment.absence.start_date}-${segment.absence.status}-${segment.startIndex}`}
                      role="cell"
                      style={{
                        gridColumn: `${segment.startIndex + 2} / span ${segment.span}`,
                        gridRow: 1,
                      }}
                      className={cn(
                        "relative z-10 mx-0.5 min-w-0",
                        segment.span === 1 && segment.half && "w-1/2",
                      )}
                    >
                      <button
                        type="button"
                        aria-label={`${person.name}: ${segment.absence.label}${
                          segment.pending ? " (czeka na akceptację)" : ""
                        }${segment.half ? " (pół dnia)" : ""} ${range}`}
                        title={`${segment.absence.label} ${range}`}
                        onClick={() => onSelect(active ? null : { person, absence: segment.absence })}
                        className={cn(
                          "flex h-6 w-full items-center overflow-hidden whitespace-nowrap rounded-md px-1.5 text-[11px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          segment.span === 1 && "justify-center px-0",
                          segment.pending
                            ? "border-[1.5px] border-dashed border-primary/60 bg-card text-primary hover:bg-primary/10"
                            : "bg-primary/25 text-primary hover:bg-primary/35",
                          active && "ring-2 ring-primary",
                        )}
                      >
                        {segment.label}
                      </button>
                    </div>
                  );
                })}
                {marks.map((mark) => (
                  <span
                    key={`${mark.kind}-${mark.index}`}
                    role="img"
                    aria-label={`${person.name}: ${PRESENCE_LABELS[mark.kind]} ${formatRange(days[mark.index], days[mark.index])}`}
                    title={PRESENCE_LABELS[mark.kind]}
                    style={{ gridColumn: mark.index + 2, gridRow: 1 }}
                    className={cn(
                      "relative z-10 mx-0.5 grid h-6 place-items-center rounded-md text-[10px] font-semibold",
                      mark.kind === "remote"
                        ? "bg-info-muted text-info-muted-foreground"
                        : "bg-warning-muted text-warning-muted-foreground",
                    )}
                  >
                    {mark.kind === "remote" ? "Z" : "W"}
                  </span>
                ))}
              </div>
            );
          })}
          <HeatRow data={data} counts={counts} style={style} background={background} />
        </div>
      </div>
    </div>
  );
}

/** Wiersz „Nieobecnych”: ile osób nie ma danego dnia (½, „?” = z wnioskiem, który czeka). */
function HeatRow({
  data,
  counts,
  style,
  background,
}: {
  data: TeamCalendarData;
  counts: Map<string, AbsentCount>;
  style: CSSProperties;
  background: ReactNode;
}) {
  return (
    <div
      role="row"
      className="grid h-[38px] items-center border-t border-border bg-muted/30"
      style={{ ...style, gridTemplateRows: "38px" }}
    >
      <div
        role="rowheader"
        style={{ gridColumn: 1, gridRow: 1 }}
        className="sticky left-0 z-20 flex h-full items-center bg-card px-3 text-xs font-semibold text-foreground"
      >
        Nieobecnych
      </div>
      {background}
      {data.days.map((day, index) => {
        const count = counts.get(day.date);
        if (!count) return null;
        return (
          <span
            key={day.date}
            role="cell"
            title={count.names.join(", ")}
            aria-label={`${formatWeekdayDayPl(day.date)}: nieobecnych ${count.text}`}
            style={{ gridColumn: index + 2, gridRow: 1 }}
            className={cn(
              "relative z-10 mx-0.5 grid h-[22px] place-items-center rounded-[5px] text-[10.5px] font-semibold tabular-nums",
              HEAT[heatLevel(count.value)],
            )}
          >
            {count.text}
          </span>
        );
      })}
    </div>
  );
}

function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

/** „W tym tygodniu nie ma” i „Najtrudniejszy dzień” — z tych samych danych co siatka. */
function SidePanel({
  data,
  people,
  today,
  todayInView,
}: {
  data: TeamCalendarData;
  people: TeamCalendarPerson[];
  today: string;
  todayInView: boolean;
}) {
  const firstWorkDay = data.days.find((day) => day.kind === "work")?.date ?? data.days[0]?.date;
  const monday = mondayOf(todayInView ? today : firstWorkDay ?? today);
  const friday = addDays(monday, 4);
  const absentees = weekAbsentees(people, monday, today);
  const counts = absentCounts(people, data.days);
  const hardest = hardestDay(counts);
  const range = `${Number(monday.slice(8, 10))}${
    monday.slice(5, 7) === friday.slice(5, 7) ? "" : `.${monday.slice(5, 7)}`
  }–${Number(friday.slice(8, 10))}.${friday.slice(5, 7)}`;
  return (
    <aside className="flex min-w-0 flex-[1_1_250px] flex-col gap-3" aria-label="Podsumowanie">
      <section className="flex flex-col gap-2.5 rounded-xl border border-border bg-card px-4 py-3.5">
        <div>
          <h2 className="font-semibold text-foreground">
            {todayInView && monday === mondayOf(today) ? "W tym tygodniu nie ma" : "W tygodniu nie ma"}
          </h2>
          <p className="text-xs text-muted-foreground">{range}</p>
        </div>
        {absentees.length === 0 ? (
          <p className="text-sm text-muted-foreground">Wszyscy na miejscu.</p>
        ) : (
          <ul className="space-y-2">
            {absentees.map((item) => (
              <li key={item.user_id} className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary"
                >
                  {personInitials(item.name)}
                </span>
                <div className="min-w-0 text-[13px] leading-tight">
                  <div className="truncate font-medium text-foreground">{item.name}</div>
                  <div className={cn("text-xs", item.pending ? "text-primary" : "text-muted-foreground")}>
                    {item.text}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      {hardest ? (
        <section className="flex flex-col gap-1.5 rounded-xl border border-border bg-card px-4 py-3.5">
          <h2 className="font-semibold text-foreground">Najtrudniejszy dzień</h2>
          <p className="text-[13px] text-foreground">
            {formatWeekdayDayPl(hardest.date)} · <b>{hardest.count.text}</b>{" "}
            {hardest.count.value >= 5 ? "osób nieobecnych" : "osoby nieobecne"}
          </p>
          <p className="text-xs text-muted-foreground">
            {hardest.count.names.map(firstName).join(", ")}
          </p>
        </section>
      ) : null}
    </aside>
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
