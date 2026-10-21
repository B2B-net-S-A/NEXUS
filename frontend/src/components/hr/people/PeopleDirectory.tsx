"use client";

import { Fragment, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Search, UserPlus, UserRoundPlus } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
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
  isFullPerson,
  usePeople,
  type EmploymentType,
  type HrConfig,
  type Person,
} from "@/lib/api/hr";
import { useSetTimesheetRequired } from "@/lib/api/hr-people";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { shortName } from "@/components/hr/leave/leave-format";

import { AccountMismatchesPanel, type PendingPerson } from "./AccountMismatchesPanel";
import { AddPersonDialog } from "./AddPersonDialog";
import {
  FORM_SHORT,
  NO_DEPARTMENT,
  departmentDot,
  formLabel,
  groupByDepartment,
  isAwayToday,
  tenureLabel,
  todayChips,
  todayKnown as absencesKnown,
} from "./directory-view";
import { PersonAvatar } from "./PersonAvatar";
import { FilterChip, TonePill } from "./people-ui";

const MODULE_OFF_NOTICE =
  "Moduł „Ludzie” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";

/** „Składa raport godzin” — tylko w pełnym zakresie (Kadry); `null` = nie widać. */
export function timesheetRequired(person: Person): boolean | null {
  return isFullPerson(person) ? person.timesheet_required : null;
}

/** Kartoteka „do uzupełnienia” (z konta): forma albo przełożony — bez zdradzania formy. */
export function needsCompletion(person: Person): boolean {
  return isFullPerson(person) && (person.employment_type_pending || Boolean(person.manager_pending));
}

type StatusFilter = "away" | "leaving" | "no_report" | null;

const FORMS: EmploymentType[] = ["b2b", "uop", "zlecenie"];

/** Kto ma kartotekę „do uzupełnienia” — do paska rozjazdów (bez zdradzania formy). */
export function pendingPeople(rows: readonly Person[]): PendingPerson[] {
  return rows.filter(needsCompletion).map((row) => {
    const full = isFullPerson(row) ? row : null;
    const what = [
      full?.employment_type_pending ? "forma" : null,
      full?.manager_pending ? "przełożony" : null,
    ].filter(Boolean);
    return { user_id: row.user_id, name: row.name, what: what.join(" i ") };
  });
}

/**
 * Katalog ludzi (makieta 19.10.2026): chipy działów i formy, grupy po dziale,
 * kolumna „Dziś” (nieobecność bez rodzaju, delegacja, odejście) i staż.
 * Zakres danych (wizytówka / pełna kartoteka, forma) wyznacza serwer.
 */
export function PeopleDirectory({ config }: { config: HrConfig }) {
  const people = usePeople();
  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState<string | null>(null);
  const [form, setForm] = useState<EmploymentType | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(null);
  const [adding, setAdding] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const { showToast } = useToast();
  const setRequired = useSetTimesheetRequired();
  const canAdd = config.me.people_admin;
  // Hurtowa flaga raportu godzin (Kadry): zaznacz osoby → „tak / nie”.
  const canBulk = canAdd;
  // Rozjazdy kartoteka ↔ konto: admin, Finanse i Kadry (19.10.2026).
  const seesAccounts = config.me.people_admin || config.me.payroll || config.me.is_admin;
  // „W pracy” i „Dziś nieobecni” tylko przy urlopach otwartych dla patrzącego.
  const todayKnown = absencesKnown(config.open_modules);
  const today = warsawToday();

  const rows = useMemo(() => people.data?.items ?? [], [people.data]);
  const searched = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("pl-PL");
    if (!needle) return rows;
    return rows.filter((row) =>
      [row.name, row.email, row.job_title, row.department, row.manager_name]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("pl-PL").includes(needle)),
    );
  }, [rows, query]);
  const filtered = useMemo(
    () =>
      searched.filter((row) => {
        if (department && (row.department?.trim() || NO_DEPARTMENT) !== department) return false;
        if (form && !(isFullPerson(row) && row.employment_type === form)) return false;
        if (statusFilter === "away" && !isAwayToday(row)) return false;
        if (statusFilter === "leaving" && row.employment_status !== "offboarding") return false;
        if (statusFilter === "no_report" && timesheetRequired(row) !== false) return false;
        return true;
      }),
    [searched, department, form, statusFilter],
  );
  const groups = useMemo(() => groupByDepartment(filtered), [filtered]);
  const departments = useMemo(() => groupByDepartment(rows).map((g) => g.department), [rows]);
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

  const deptCounts = groupByDepartment(searched);
  const formCounts = FORMS.map((value) => ({
    value,
    count: searched.filter((row) => isFullPerson(row) && row.employment_type === value).length,
  })).filter((item) => item.count > 0);
  const awayCount = searched.filter(isAwayToday).length;
  const leavingCount = searched.filter((row) => row.employment_status === "offboarding").length;
  const noReportCount = searched.filter((row) => timesheetRequired(row) === false).length;
  const showForm = rows.some((row) => formLabel(row) != null);
  const grouped = departments.length > 1;
  const columns = 5 + (showForm ? 1 : 0) + (canBulk ? 1 : 0);

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
  const toggleStatus = (value: Exclude<StatusFilter, null>) =>
    setStatusFilter((current) => (current === value ? null : value));

  return (
    <div className="space-y-3">
      {canAdd ? (
        <div className="flex flex-wrap justify-end gap-2">
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

      {seesAccounts ? <AccountMismatchesPanel pendingPeople={pendingPeople(rows)} /> : null}

      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative w-full max-w-[300px]">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj osoby"
            placeholder="Imię, stanowisko, przełożony"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-8"
          />
        </div>
        <div role="group" aria-label="Filtry katalogu" className="flex flex-1 flex-wrap items-center gap-1.5">
          <FilterChip
            active={department === null}
            count={searched.length}
            onClick={() => setDepartment(null)}
          >
            Wszyscy
          </FilterChip>
          {grouped
            ? deptCounts.map((group) => (
                <FilterChip
                  key={group.department}
                  active={department === group.department}
                  count={group.rows.length}
                  dotClass={departmentDot(group.department, departments)}
                  onClick={() =>
                    setDepartment((current) =>
                      current === group.department ? null : group.department,
                    )
                  }
                >
                  {group.department}
                </FilterChip>
              ))
            : null}
          {formCounts.length > 0 ? (
            <span aria-hidden className="mx-1 h-5 w-px bg-border" />
          ) : null}
          {formCounts.map((item) => (
            <FilterChip
              key={item.value}
              active={form === item.value}
              count={item.count}
              onClick={() => setForm((current) => (current === item.value ? null : item.value))}
            >
              {FORM_SHORT[item.value]}
            </FilterChip>
          ))}
          <span aria-hidden className="mx-1 h-5 w-px bg-border" />
          {todayKnown ? (
            <FilterChip
              active={statusFilter === "away"}
              count={awayCount}
              onClick={() => toggleStatus("away")}
            >
              Dziś nieobecni
            </FilterChip>
          ) : null}
          {leavingCount > 0 ? (
            <FilterChip
              active={statusFilter === "leaving"}
              count={leavingCount}
              onClick={() => toggleStatus("leaving")}
            >
              Odchodzą
            </FilterChip>
          ) : null}
          {canBulk && noReportCount > 0 ? (
            <FilterChip
              active={statusFilter === "no_report"}
              count={noReportCount}
              onClick={() => toggleStatus("no_report")}
            >
              Bez raportu godzin
            </FilterChip>
          ) : null}
        </div>
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
          <Table density="compact" className="min-w-[960px]">
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
                {showForm ? <TableHead className={CALM_HEAD}>Forma</TableHead> : null}
                <TableHead className={CALM_HEAD}>Przełożony</TableHead>
                <TableHead className={CALM_HEAD}>Dziś</TableHead>
                <TableHead className={CALM_HEAD}>W firmie</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map((group) => (
                <Fragment key={group.department}>
                  {grouped ? (
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableCell colSpan={columns} className="py-1.5">
                        <span className="flex items-center gap-2 text-xs font-semibold text-foreground">
                          <span
                            aria-hidden
                            className={`h-2 w-2 rounded-full ${departmentDot(group.department, departments)}`}
                          />
                          {group.department}
                          <span className="font-medium text-muted-foreground">
                            · {group.rows.length}
                          </span>
                        </span>
                      </TableCell>
                    </TableRow>
                  ) : null}
                  {group.rows.map((row) => (
                    <DirectoryRow
                      key={row.user_id}
                      row={row}
                      today={today}
                      todayKnown={todayKnown}
                      showForm={showForm}
                      canBulk={canBulk}
                      selected={selected.has(row.user_id)}
                      onSelect={(checked) => toggleOne(row.user_id, checked)}
                    />
                  ))}
                </Fragment>
              ))}
            </TableBody>
          </Table>
          {filtered.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              {query.trim() ? `Nikt nie pasuje do „${query}”.` : "Nikt nie pasuje do filtrów."}
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

function DirectoryRow({
  row,
  today,
  todayKnown,
  showForm,
  canBulk,
  selected,
  onSelect,
}: {
  row: Person;
  today: string;
  todayKnown: boolean;
  showForm: boolean;
  canBulk: boolean;
  selected: boolean;
  onSelect: (checked: boolean) => void;
}) {
  const full = isFullPerson(row) ? row : null;
  const chips = todayChips(row, today, todayKnown);
  const formText = formLabel(row);
  const tenure = full ? tenureLabel(full.work_start_date ?? full.hired_on, today) : null;
  const noReport = canBulk && timesheetRequired(row) === false;
  return (
    <TableRow className={`${CALM_ROW} h-[50px] ${needsCompletion(row) ? "bg-warning-muted/20" : ""}`}>
      {canBulk ? (
        <TableCell className="w-9">
          <Checkbox
            aria-label={`Zaznacz: ${row.name}`}
            checked={selected}
            onCheckedChange={(checked) => onSelect(checked === true)}
          />
        </TableCell>
      ) : null}
      <TableCell>
        <Link
          href={`/people/${row.user_id}`}
          className="flex min-w-0 items-center gap-2.5 hover:underline"
        >
          <PersonAvatar name={row.name} />
          <span className="min-w-0">
            <span className="block truncate font-medium text-foreground">{row.name}</span>
            <span className={`${CALM_SUBLINE} truncate`}>{row.email}</span>
          </span>
        </Link>
        {noReport ? (
          <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-warning-muted-foreground">
            <AlertTriangle className="h-3 w-3" aria-hidden />
            nie składa raportu godzin
          </span>
        ) : null}
      </TableCell>
      <TableCell>{row.job_title ?? <span className={CALM_EMPTY}>—</span>}</TableCell>
      {showForm ? (
        <TableCell>
          {formText ? (
            <TonePill tone={formText === "uzupełnij" ? "warning" : "neutral"}>{formText}</TonePill>
          ) : (
            <span className={CALM_EMPTY}>—</span>
          )}
        </TableCell>
      ) : null}
      <TableCell>
        {row.manager_name && row.manager_user_id ? (
          <Link
            href={`/people/${row.manager_user_id}`}
            className="inline-flex items-center gap-1.5 hover:underline"
            title={row.manager_name}
          >
            <PersonAvatar name={row.manager_name} size="xs" />
            {shortName(row.manager_name)}
          </Link>
        ) : full?.manager_pending ? (
          <span className="text-xs text-warning-muted-foreground">przełożony do uzupełnienia</span>
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
      </TableCell>
      <TableCell>
        {chips.length === 0 ? (
          <span className={CALM_EMPTY}>—</span>
        ) : (
          <span className="flex flex-wrap items-center gap-1.5">
            {chips.map((chip) =>
              chip.label === "w pracy" ? (
                <span key={chip.label} className="inline-flex items-center gap-1.5 text-sm">
                  <span aria-hidden className="h-2 w-2 rounded-full bg-success" />
                  w pracy
                </span>
              ) : (
                <TonePill key={chip.label} tone={chip.tone}>
                  {chip.label}
                </TonePill>
              ),
            )}
          </span>
        )}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">{tenure ?? "—"}</TableCell>
    </TableRow>
  );
}
