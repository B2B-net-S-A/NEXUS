"use client";

import { useState } from "react";
import Link from "next/link";

import { InlineStats } from "@/components/ds/InlineStats";
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
import { useMyTeam, useTeamManagers, type MyTeam } from "@/lib/api/hr-team";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { useUrlWriter } from "@/lib/url-selection";
import { resolveViewState } from "@/lib/view-state";

import { bonusCell, decisionItems, leaveCell, monthCell, todayCell, type Cell } from "./team-format";

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

/**
 * „Ludzie → Mój zespół”: przełożony o swoich bezpośrednich podwładnych.
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
      <SelectTrigger className="h-9 w-full max-w-xs" aria-label="Zespół przełożonego">
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
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        {picker}
        {state === "empty" ? null : <TeamStats data={data} />}
      </div>
      {state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {data.is_own
            ? "Nikt nie ma Cię wpisanego jako przełożonego ani koordynatora."
            : `${data.manager.name} nie ma podwładnych z kartoteką.`}
        </div>
      ) : (
        <TeamTable data={data} />
      )}
      <p className="text-xs text-muted-foreground">
        Rodzaj nieobecności widzą tylko osoba, jej przełożony albo koordynator i Kadry. Kwoty
        premii widać bez stawek godzinowych; o propozycjach premii decydują Płace.
      </p>
    </div>
  );
}

function TeamStats({ data }: { data: MyTeam }) {
  const stats = [
    { id: "people", label: "osób", value: data.stats.people },
    ...(data.modules.leave
      ? [
          { id: "absent", label: "dziś nieobecnych", value: data.stats.absent_today },
          { id: "leave", label: "wnioski do decyzji", value: data.stats.leave_requests },
        ]
      : []),
    ...(data.modules.time
      ? [{ id: "timesheets", label: "timesheety do akceptacji", value: data.stats.timesheets }]
      : []),
    ...(data.stats.bonus_proposals !== null
      ? [{ id: "bonuses", label: "propozycje premii", value: data.stats.bonus_proposals }]
      : []),
  ];
  return <InlineStats stats={stats} />;
}

function TeamTable({ data }: { data: MyTeam }) {
  const monthName = data.month
    ? new Intl.DateTimeFormat("pl-PL", { month: "long", timeZone: "UTC" }).format(
        new Date(Date.UTC(data.month.year, data.month.month - 1, 1)),
      )
    : "Miesiąc";
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className="min-w-[960px]">
        <TableHeader>
          <TableRow>
            <TableHead className={CALM_HEAD}>Osoba</TableHead>
            <TableHead className={CALM_HEAD}>Dziś</TableHead>
            <TableHead className={CALM_HEAD}>Nieobecności</TableHead>
            <TableHead className={`${CALM_HEAD} capitalize`}>{monthName}</TableHead>
            {data.sees_bonuses ? (
              <TableHead className={CALM_HEAD}>Premie w drodze</TableHead>
            ) : null}
            <TableHead className={CALM_HEAD}>Do decyzji</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.people.map((person) => {
            const decisions = decisionItems(person);
            return (
              <TableRow key={person.user_id} className={`${CALM_ROW} align-top`}>
                <TableCell>
                  <Link href={`/people/${person.user_id}`} className="font-medium text-foreground hover:underline">
                    {person.name}
                  </Link>
                  <span className={CALM_SUBLINE}>
                    {[
                      person.job_title,
                      person.employment_type
                        ? EMPLOYMENT_TYPE_SHORT[person.employment_type]
                        : null,
                      person.student ? "student" : null,
                      person.employment_status === "offboarding" ? "odchodzi" : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </TableCell>
                <TableCell>
                  <CellView cell={todayCell(person.today, person.covering_for)} />
                </TableCell>
                <TableCell>
                  <CellView cell={leaveCell(person.leave, person.employment_type ?? undefined)} />
                </TableCell>
                <TableCell>
                  <CellView cell={monthCell(person, data)} />
                </TableCell>
                {data.sees_bonuses ? (
                  <TableCell>
                    <CellView cell={bonusCell(person.bonuses)} />
                  </TableCell>
                ) : null}
                <TableCell>
                  {decisions.length === 0 ? (
                    <span className={CALM_EMPTY}>—</span>
                  ) : (
                    <ul className="space-y-0.5">
                      {decisions.map((item) => (
                        <li key={item.key}>
                          <Link href={item.href} className="text-primary hover:underline">
                            {item.text}
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
