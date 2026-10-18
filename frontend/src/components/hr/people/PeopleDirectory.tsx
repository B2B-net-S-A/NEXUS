"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Search, UserPlus, UserRoundPlus } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  EMPLOYMENT_STATUS_LABELS,
  LOCATION_LABELS,
  isFullPerson,
  usePeople,
  type HrConfig,
  type Person,
} from "@/lib/api/hr";
import { useSetTimesheetRequired } from "@/lib/api/hr-people";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";

import { AbsenceBadge } from "@/components/hr/AbsenceBadge";
import { useAbsences } from "@/lib/api/hr-leave";

import { AddPersonDialog } from "./AddPersonDialog";
import { STATUS_TONE, personInitials } from "./hr-format";

const MODULE_OFF_NOTICE =
  "Moduł „Ludzie” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";

/** „Składa raport godzin” — tylko w pełnym zakresie (Kadry); `null` = nie widać. */
export function timesheetRequired(person: Person): boolean | null {
  return isFullPerson(person) ? person.timesheet_required : null;
}

/** Katalog ludzi: wizytówki osób zatrudnionych (pełne dane w zakresie czytającego). */
export function PeopleDirectory({ config }: { config: HrConfig }) {
  const people = usePeople();
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const { showToast } = useToast();
  const setRequired = useSetTimesheetRequired();
  const canAdd = config.me.people_admin;
  // Hurtowa flaga raportu godzin (Kadry): zaznacz osoby → „tak / nie”.
  const canBulk = canAdd;
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
  const withoutReport = rows.filter((row) => timesheetRequired(row) === false).length;

  const visibleSelected = filtered.filter((row) => selected.has(row.user_id)).length;
  const allVisible = filtered.length > 0 && visibleSelected === filtered.length;
  const toggleAll = (checked: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      for (const row of filtered) {
        if (checked) next.add(row.user_id);
        else next.delete(row.user_id);
      }
      return next;
    });
  const toggleOne = (userId: number, checked: boolean) =>
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(userId);
      else next.delete(userId);
      return next;
    });
  const applyRequired = (required: boolean) => {
    const ids = [...selected];
    setRequired.mutate(
      { user_ids: ids, required },
      {
        onSuccess: (result) => {
          showToast(
            result.changed.length > 0
              ? `${required ? "Składa" : "Nie składa"} raportu godzin: ${countPl(result.changed.length, "osoba", "osoby", "osób")}.`
              : "Bez zmian — zaznaczone osoby już tak miały.",
            "success",
          );
          setSelected(new Set());
        },
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zmienić raportu godzin."), "error"),
      },
    );
  };

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
            ...(canBulk
              ? [{ id: "no-report", label: "bez raportu godzin", value: withoutReport }]
              : []),
          ]}
        />
        {canAdd ? (
          <div className="ml-auto flex flex-wrap gap-2">
            {/* Wejście nowej osoby = kreator z zadaniami (moduł wejścia/odejścia). */}
            {config.open_modules.lifecycle ? (
              <Button variant="outline" asChild>
                <Link href="/people/new">
                  <UserRoundPlus className="h-4 w-4" aria-hidden />
                  Wejście nowej osoby
                </Link>
              </Button>
            ) : null}
            <Button onClick={() => setAdding(true)}>
              <UserPlus className="h-4 w-4" aria-hidden />
              Dodaj osobę
            </Button>
          </div>
        ) : null}
      </div>

      {canBulk && selected.size > 0 ? (
        <div
          role="region"
          aria-label="Zaznaczone osoby"
          className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm"
        >
          <span className="font-medium text-foreground">
            Zaznaczono: {countPl(selected.size, "osoba", "osoby", "osób")}
          </span>
          <span className="text-muted-foreground">Składa raport godzin:</span>
          <Button
            size="sm"
            variant="outline"
            disabled={setRequired.isPending}
            onClick={() => applyRequired(true)}
          >
            Tak
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={setRequired.isPending}
            onClick={() => applyRequired(false)}
          >
            Nie
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={() => setSelected(new Set())}
          >
            Odznacz
          </Button>
        </div>
      ) : null}

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
                {canBulk ? (
                  <TableHead className="w-9">
                    <Checkbox
                      aria-label="Zaznacz wszystkich widocznych"
                      checked={allVisible ? true : visibleSelected > 0 ? "indeterminate" : false}
                      onCheckedChange={(checked) => toggleAll(checked === true)}
                    />
                  </TableHead>
                ) : null}
                <TableHead className={CALM_HEAD}>Osoba</TableHead>
                <TableHead className={CALM_HEAD}>Stanowisko</TableHead>
                <TableHead className={CALM_HEAD}>Przełożony</TableHead>
                <TableHead className={CALM_HEAD}>Domyślnie</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
                {canBulk ? <TableHead className={CALM_HEAD}>Raport godzin</TableHead> : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((row) => (
                <TableRow key={row.user_id} className={`${CALM_ROW} h-[50px]`}>
                  {canBulk ? (
                    <TableCell className="w-9">
                      <Checkbox
                        aria-label={`Zaznacz: ${row.name}`}
                        checked={selected.has(row.user_id)}
                        onCheckedChange={(checked) => toggleOne(row.user_id, checked === true)}
                      />
                    </TableCell>
                  ) : null}
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
                  {canBulk ? (
                    <TableCell>
                      {timesheetRequired(row) == null ? (
                        <span className={CALM_EMPTY}>—</span>
                      ) : timesheetRequired(row) ? (
                        "tak"
                      ) : (
                        <span className="text-muted-foreground">nie składa</span>
                      )}
                    </TableCell>
                  ) : null}
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
