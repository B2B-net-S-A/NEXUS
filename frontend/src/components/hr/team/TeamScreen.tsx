"use client";

import { useState } from "react";
import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { HrConfig } from "@/lib/api/hr";
import { EMPLOYMENT_TYPE_SHORT } from "@/lib/api/hr-structure";
import { useMyTeam, useTeamManagers, type MyTeam, type TeamPerson } from "@/lib/api/hr-team";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, formatWeekdayDayPl } from "@/lib/date-pl";
import { useUrlWriter } from "@/lib/url-selection";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { personInitials } from "../people/hr-format";
import { TeamDecisions } from "./TeamDecisions";
import { bonusCell, leaveCell, type Cell } from "./team-format";
import {
  missingDaysLabel,
  monthProgress,
  todayStatus,
  todaySummary,
  weekAriaLabel,
  weekCells,
  type TodayKind,
} from "./team-week";

function CellView({ cell }: { cell: Cell }) {
  return (
    <>
      <span
        className={
          cell.tone === "muted"
            ? CALM_EMPTY
            : cell.tone === "warning"
              ? "text-warning-muted-foreground"
              : "text-foreground"
        }
      >
        {cell.text}
      </span>
      {cell.sub ? <span className={CALM_SUBLINE}>{cell.sub}</span> : null}
    </>
  );
}

function Avatar({ name, size = "md", className }: { name: string; size?: "sm" | "md"; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center rounded-full bg-primary/10 font-semibold text-primary",
        size === "sm" ? "h-[30px] w-[30px] text-[11px]" : "h-9 w-9 text-xs",
        className,
      )}
    >
      {personInitials(name)}
    </span>
  );
}

/**
 * „Ludzie → Mój zespół” (makieta 19.10.2026, wiersze decyzji 22.10.2026): pasek
 * „Dziś”, zwarte wiersze „Do Twojej decyzji” z akceptacją na miejscu, tabela
 * z mini-tygodniem i paskiem godzin; imię otwiera profil na nieobecnościach i godzinach.
 * Kadry i admin wybierają przełożonego (`?manager=`).
 */
export function TeamScreen({
  config,
  initialManager,
}: {
  config: HrConfig;
  initialManager: number | null;
}) {
  const canAny = config.me.people_admin || config.me.is_admin;
  const [managerId, setManagerId] = useState<number | null>(canAny ? initialManager : null);
  const { replaceUrl } = useUrlWriter();
  const team = useMyTeam(managerId);
  const managers = useTeamManagers(canAny);

  const state = resolveViewState({
    isLoading: team.isLoading,
    isError: team.isError,
    error: team.error,
    isSuccess: team.isSuccess,
    isEmpty: (team.data?.people.length ?? 0) === 0,
  });

  const picker = canAny ? (
    <Select
      value={managerId ? String(managerId) : "me"}
      onValueChange={(value) => {
        const next = value === "me" ? null : Number(value);
        setManagerId(next);
        replaceUrl(next ? `?manager=${next}` : window.location.pathname);
      }}
    >
      <SelectTrigger className="h-9 w-full max-w-xs" aria-label="Zespół koordynatora">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="me">Mój zespół</SelectItem>
        {(managers.data ?? []).map((item) => (
          <SelectItem key={item.user_id} value={String(item.user_id)}>
            {item.name} · {item.reports}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  ) : null;

  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie zespołu…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !team.data) {
    return (
      <div className="space-y-3">
        {picker}
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={
            state === "forbidden"
              ? "„Mój zespół” widzą przełożeni i Kadry."
              : state === "not_found"
                ? "Moduł „Ludzie” nie jest jeszcze włączony albo nie ma takiej osoby."
                : undefined
          }
          onRetry={() => team.refetch()}
        />
      </div>
    );
  }
  const data = team.data;
  return (
    <div className="space-y-4">
      {picker ? <div className="flex flex-wrap items-center gap-3">{picker}</div> : null}
      {state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {data.is_own
            ? "Nikt nie ma Cię wpisanego jako koordynatora."
            : `${data.manager.name} nie ma w zespole osób z kartoteką.`}
        </div>
      ) : (
        <>
          <TodayStrip data={data} />
          <TeamDecisions team={data} />
          <TeamTable data={data} />
        </>
      )}
      <p className="text-xs text-muted-foreground">
        Rodzaj nieobecności widzą tylko osoba, jej przełożony albo koordynator i Kadry. Kwoty
        premii widać bez stawek godzinowych; o propozycjach premii decydują Płace.
      </p>
    </div>
  );
}

const RING: Record<TodayKind, string> = {
  work: "ring-success",
  absent: "ring-primary/40 opacity-70",
  trip: "ring-warning",
  remote: "ring-info",
  unknown: "ring-border",
};

const TODAY_TEXT: Record<TodayKind, string> = {
  work: "text-muted-foreground",
  absent: "text-primary",
  trip: "text-warning-muted-foreground",
  remote: "text-info-muted-foreground",
  unknown: "text-muted-foreground",
};

/** Pasek „Dziś”: awatar z obwódką stanu i jedno zdanie (rodzaj tylko z serwera, D6). */
function TodayStrip({ data }: { data: MyTeam }) {
  if (!data.modules.leave && !data.week) return null;
  return (
    <section
      aria-label="Dziś"
      className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl border border-border bg-card px-4 py-3"
    >
      <div className="flex flex-col">
        <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Dziś · {formatWeekdayDayPl(data.today)}
        </span>
        <span className="text-sm text-foreground">{todaySummary(data.people, data.today)}</span>
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-2">
        {data.people.map((person) => {
          const status = todayStatus(person, data.today);
          return (
            <li key={person.user_id} className="flex items-center gap-2">
              <Avatar
                name={person.name}
                className={cn("ring-2 ring-offset-2 ring-offset-card", RING[status.kind])}
              />
              <div className="text-sm leading-tight">
                <div className="font-medium text-foreground">{person.name.split(/\s+/)[0]}</div>
                <div className={cn("text-xs", TODAY_TEXT[status.kind])}>{status.text}</div>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

const WEEK_CELL: Record<string, string> = {
  work: "bg-success-muted text-success-muted-foreground",
  off: "bg-muted text-muted-foreground/70",
  absent: "bg-primary/20 text-primary",
  pending: "border border-dashed border-primary/60 bg-card text-primary",
  business_trip: "bg-warning-muted text-warning-muted-foreground",
  remote: "bg-info-muted text-info-muted-foreground",
  unknown: "border border-border bg-card text-muted-foreground",
};

/** Mini-tydzień pn–pt; dziś obrysowane. */
function WeekStrip({ person, today }: { person: TeamPerson; today: string }) {
  const cells = weekCells(person, today);
  if (!cells) return <span className={CALM_EMPTY}>—</span>;
  return (
    <div role="img" aria-label={weekAriaLabel(cells)} className="grid w-max grid-cols-5 gap-[3px]">
      {cells.map((cell) => (
        <span
          key={cell.date}
          title={cell.title}
          className={cn(
            "grid h-[22px] w-[22px] place-items-center rounded-[5px] text-[10px] font-semibold",
            WEEK_CELL[cell.state],
            cell.isToday && "outline outline-2 outline-offset-1 outline-primary",
          )}
        >
          {cell.mark}
        </span>
      ))}
    </div>
  );
}

function MonthBar({ person, data }: { person: TeamPerson; data: MyTeam }) {
  const progress = monthProgress(person, data);
  if (!progress) return <span className={CALM_EMPTY}>—</span>;
  if (progress.hours === null) return <span className={CALM_EMPTY}>{progress.text}</span>;
  const missing = missingDaysLabel(person.month?.missing_dates);
  return (
    <div className="min-w-[140px] space-y-1">
      <div className="flex items-center justify-between gap-2 text-[13px]">
        <span className="tabular-nums text-foreground">{progress.text}</span>
        {missing ? (
          <span
            className="rounded-full bg-warning-muted px-2 py-px text-[11px] font-medium text-warning-muted-foreground"
            data-testid="team-missing-days"
          >
            {missing}
          </span>
        ) : null}
        {progress.status === "submitted" ? (
          <span className="rounded-full bg-info-muted px-2 py-px text-[11px] font-medium text-info-muted-foreground">
            {progress.statusLabel}
          </span>
        ) : progress.status === "approved" ? (
          <span className="rounded-full bg-success-muted px-2 py-px text-[11px] font-medium text-success-muted-foreground">
            {progress.statusLabel}
          </span>
        ) : progress.status === "missing" ? (
          <span className="rounded-full bg-warning-muted px-2 py-px text-[11px] font-medium text-warning-muted-foreground">
            {progress.statusLabel}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">{progress.statusLabel}</span>
        )}
      </div>
      <div
        role="progressbar"
        aria-label={`Godziny: ${progress.text}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress.percent}
        className="h-1.5 overflow-hidden rounded-full bg-muted"
      >
        <span
          className={cn("block h-full rounded-full", progress.full ? "bg-success" : "bg-primary")}
          style={{ width: `${progress.percent}%` }}
        />
      </div>
    </div>
  );
}

function personSubline(person: TeamPerson): { text: string; warning: boolean } {
  const offboarding = person.employment_status === "offboarding";
  const text = [
    person.job_title,
    person.employment_type ? EMPLOYMENT_TYPE_SHORT[person.employment_type] : null,
    person.student ? "student" : null,
    offboarding
      ? person.last_working_day
        ? `odchodzi ${formatDayMonthPl(person.last_working_day)}`
        : "odchodzi"
      : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return { text, warning: offboarding };
}

function TeamTable({ data }: { data: MyTeam }) {
  const monthName = data.month
    ? new Intl.DateTimeFormat("pl-PL", { month: "long", timeZone: "UTC" }).format(
        new Date(Date.UTC(data.month.year, data.month.month - 1, 1)),
      )
    : "Miesiąc";
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card">
      <Table density="compact" className="min-w-[880px]">
        <TableHeader>
          <TableRow className="bg-muted/40">
            <TableHead className={CALM_HEAD}>Osoba</TableHead>
            <TableHead className={`${CALM_HEAD} w-[140px]`}>Ten tydzień</TableHead>
            <TableHead className={CALM_HEAD}>{monthName}</TableHead>
            <TableHead className={CALM_HEAD}>Nieobecności</TableHead>
            {data.sees_bonuses ? (
              <TableHead className={CALM_HEAD}>Premie w drodze</TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.people.map((person) => {
            const sub = personSubline(person);
            const pending = person.to_decide.leave_requests.length;
            const leave = leaveCell(person.leave, person.employment_type ?? undefined);
            return (
              <TableRow key={person.user_id} className={CALM_ROW}>
                <TableCell className="py-2.5">
                  <div className="flex items-center gap-2.5">
                    <Avatar name={person.name} size="sm" />
                    <div className="min-w-0">
                      {/* Zakładka „Nieobecności i godziny” profilu (kotwica `#czas`). */}
                      <Link
                        href={`/people/${person.user_id}#czas`}
                        className="font-medium text-foreground hover:underline"
                      >
                        {person.name}
                      </Link>
                      {sub.text ? (
                        <span
                          className={cn(CALM_SUBLINE, sub.warning && "text-warning-muted-foreground")}
                        >
                          {sub.text}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="py-2.5">
                  <WeekStrip person={person} today={data.today} />
                </TableCell>
                <TableCell className="py-2.5">
                  <MonthBar person={person} data={data} />
                </TableCell>
                <TableCell className="py-2.5">
                  <CellView
                    cell={
                      pending > 0 && !leave.sub
                        ? {
                            ...leave,
                            sub: `${pending === 1 ? "wniosek czeka" : `${pending} wnioski czekają`} na decyzję`,
                          }
                        : leave
                    }
                  />
                </TableCell>
                {data.sees_bonuses ? (
                  <TableCell className="py-2.5">
                    <CellView cell={bonusCell(person.bonuses)} />
                  </TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
