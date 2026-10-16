"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Search, UserPlus } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  EMPLOYMENT_STATUS_LABELS,
  LOCATION_LABELS,
  usePeople,
  type HrConfig,
} from "@/lib/api/hr";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import { AbsenceBadge } from "@/components/hr/AbsenceBadge";
import { useAbsences } from "@/lib/api/hr-leave";

import { AddPersonDialog } from "./AddPersonDialog";
import { STATUS_TONE, personInitials } from "./hr-format";

const MODULE_OFF_NOTICE =
  "Moduł „Ludzie” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";

/** Katalog ludzi: wizytówki osób zatrudnionych (pełne dane w zakresie czytającego). */
export function PeopleDirectory({ config }: { config: HrConfig }) {
  const people = usePeople();
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const canAdd = config.me.people_admin;
  const absences = useAbsences(
    (people.data?.items ?? []).map((row) => row.user_id),
    { enabled: config.open_modules.leave },
  );

  const rows = useMemo(() => people.data?.items ?? [], [people.data]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("pl-PL");
    if (!needle) return rows;
    return rows.filter((row) =>
      [row.name, row.email, row.job_title, row.department, row.manager_name]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("pl-PL").includes(needle)),
    );
  }, [rows, query]);
  const managers = useMemo(
    () => rows.map((row) => ({ user_id: row.user_id, name: row.name })),
    [rows],
  );

  const state = resolveViewState({
    isLoading: people.isLoading,
    isError: people.isError,
    error: people.error,
    isSuccess: people.isSuccess,
    isEmpty: rows.length === 0,
  });

  if (state === "loading") {
    return <p className="py-6 text-sm text-muted-foreground">Wczytywanie ludzi…</p>;
  }
  if (state === "not_found") {
    return <QueryStateNotice state="not_found" description={MODULE_OFF_NOTICE} />;
  }
  if (state === "forbidden" || state === "error") {
    return (
      <QueryStateNotice
        state={state}
        description={
          state === "forbidden"
            ? "Katalog ludzi widzą osoby z kartoteką pracownika i Kadry."
            : "Nie udało się wczytać katalogu ludzi."
        }
        onRetry={() => people.refetch()}
      />
    );
  }

  const remote = rows.filter((row) => row.default_location === "remote").length;
  const leaving = rows.filter((row) => row.employment_status === "offboarding").length;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-sm">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj osoby"
            placeholder="Imię, stanowisko, dział, przełożony…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-8"
          />
        </div>
        <InlineStats
          stats={[
            { id: "people", label: "osób", value: rows.length },
            { id: "remote", label: "domyślnie zdalnie", value: remote },
            { id: "leaving", label: "w trakcie odejścia", value: leaving },
          ]}
        />
        {canAdd ? (
          <Button className="ml-auto" onClick={() => setAdding(true)}>
            <UserPlus className="h-4 w-4" aria-hidden />
            Dodaj osobę
          </Button>
        ) : null}
      </div>

      {state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {canAdd
            ? "Nikt nie ma jeszcze kartoteki. Dodaj osoby albo zaimportuj je z Compassa (Ustawienia → Import z Compassa)."
            : "Kartoteki pracowników nie zostały jeszcze założone."}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[860px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Osoba</TableHead>
                <TableHead className={CALM_HEAD}>Stanowisko</TableHead>
                <TableHead className={CALM_HEAD}>Przełożony</TableHead>
                <TableHead className={CALM_HEAD}>Domyślnie</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((row) => (
                <TableRow key={row.user_id} className={`${CALM_ROW} h-[50px]`}>
                  <TableCell>
                    <Link
                      href={`/people/${row.user_id}`}
                      className="flex min-w-0 items-center gap-2.5 hover:underline"
                    >
                      <span
                        aria-hidden
                        className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary/10 text-[11px] font-semibold text-primary"
                      >
                        {personInitials(row.name)}
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-foreground">
                          {row.name}
                        </span>
                        <span className={`${CALM_SUBLINE} truncate`}>{row.email}</span>
                        <AbsenceBadge
                          absence={absences.byUser.get(row.user_id)}
                          className="mt-0.5"
                        />
                      </span>
                    </Link>
                  </TableCell>
                  <TableCell>
                    {row.job_title ?? <span className={CALM_EMPTY}>—</span>}
                    {row.department ? (
                      <span className={CALM_SUBLINE}>{row.department}</span>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    {row.manager_name ?? <span className={CALM_EMPTY}>—</span>}
                  </TableCell>
                  <TableCell>{LOCATION_LABELS[row.default_location]}</TableCell>
                  <TableCell>
                    <StatusDot tone={STATUS_TONE[row.employment_status]}>
                      {EMPLOYMENT_STATUS_LABELS[row.employment_status]}
                    </StatusDot>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {filtered.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              Nikt nie pasuje do „{query}”.
            </p>
          ) : null}
        </div>
      )}

      {canAdd ? (
        <AddPersonDialog open={adding} onOpenChange={setAdding} managers={managers} />
      ) : null}
    </div>
  );
}
