"use client";

import { Fragment, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Search } from "lucide-react";

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
import { DivisionDialog, ReassignDialog } from "@/components/hr/structure/StructureDialogs";
import { StructureScreen } from "@/components/hr/structure/StructureScreen";
import { apiErrorMessage } from "@/lib/api-error";
import {
  isFullPerson,
  usePeople,
  type EmploymentType,
  type HrConfig,
  type Person,
} from "@/lib/api/hr";
import { useSetTimesheetRequired } from "@/lib/api/hr-people";
import { managerWords, useHrStructure, type StructurePerson } from "@/lib/api/hr-structure";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { shortName } from "@/components/hr/leave/leave-format";

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
import { useDirectoryFilters, type DirectoryView, type StatusFilter } from "./directory-url";
import { PersonAvatar } from "./PersonAvatar";
import { FilterChip, TonePill } from "./people-ui";
import { canSeeStructure, needsCompletion } from "./tidy-up";

export { needsCompletion, pendingPeople } from "./tidy-up";

const MODULE_OFF_NOTICE =
  "Moduł „Ludzie” nie jest jeszcze włączony. Włącza go administrator w Ustawieniach → Kadry.";

/** „Składa raport godzin” — tylko w pełnym zakresie (Kadry); `null` = nie widać. */
export function timesheetRequired(person: Person): boolean | null {
  return isFullPerson(person) ? person.timesheet_required : null;
}

const FORMS: EmploymentType[] = ["b2b", "uop", "zlecenie"];

const VIEWS: readonly (readonly [DirectoryView, string])[] = [
  ["lista", "Lista"],
  ["schemat", "Schemat"],
];

type BulkDialog = { kind: "reassign" | "division"; people: StructurePerson[] } | null;

/**
 * Katalog ludzi (makieta 19.10.2026): chipy działów i formy, grupy po dziale,
 * kolumna „Dziś” (nieobecność bez rodzaju, delegacja, odejście) i staż.
 * Zakres danych (wizytówka / pełna kartoteka, forma) wyznacza serwer.
 *
 * 22.10.2026: Kadry i admin przełączają „Lista | Schemat” (schemat = dawna
 * zakładka „Struktura”); w „Liście” zaznaczonym ustawiają pion i koordynatora.
 * Filtry i widok stoją w adresie, więc „← Ludzie” wraca do tej samej listy.
 */
export function PeopleDirectory({
  config,
  defaultView = "lista",
}: {
  config: HrConfig;
  /** Widok bez `?view=` w adresie (harness Struktury otwiera się na schemacie). */
  defaultView?: DirectoryView;
}) {
  const people = usePeople();
  const [filters, update] = useDirectoryFilters(defaultView);
  const { q: query, department, form, status: statusFilter } = filters;
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [bulkDialog, setBulkDialog] = useState<BulkDialog>(null);
  const { showToast } = useToast();
  const setRequired = useSetTimesheetRequired();
  // Hurtowa flaga raportu godzin (Kadry): zaznacz osoby → „tak / nie”.
  const canBulk = config.me.people_admin;
  // Schemat i hurtowa zmiana pionu / koordynatora: Kadry i admin (dawna „Struktura”).
  const canStructure = canSeeStructure(config);
  const structure = useHrStructure(canStructure);
  const selectable = canBulk || canStructure;
  const view: DirectoryView = canStructure ? filters.view : "lista";
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

  const state = resolveViewState({
    isLoading: people.isLoading,
    isError: people.isError,
    error: people.error,
    isSuccess: people.isSuccess,
    isEmpty: rows.length === 0,
  });

  const viewSwitch = canStructure ? (
    <div
      role="group"
      aria-label="Widok katalogu"
      className="ml-auto inline-flex shrink-0 rounded-lg border border-border bg-card p-0.5"
    >
      {VIEWS.map(([value, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={view === value}
          onClick={() => update({ view: value })}
          className={cn(
            "h-8 rounded-md px-3 text-[13px] font-medium transition-colors",
            view === value
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {label}
        </button>
      ))}
    </div>
  ) : null;

  // Schemat nie czeka na katalog — ma własny odczyt i własne stany.
  if (view === "schemat") {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2.5">{viewSwitch}</div>
        <StructureScreen config={config} />
      </div>
    );
  }

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
            ? "Katalog ludzi widzą osoby z kartoteką w NEXUSIE i Kadry."
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
  const columns = 5 + (showForm ? 1 : 0) + (selectable ? 1 : 0);

  const visibleSelected = filtered.filter((row) => selected.has(row.user_id)).length;
  const allVisible = filtered.length > 0 && visibleSelected === filtered.length;
  // Zaznaczeni z kartoteką w strukturze (odczyt Struktury; bez niego nie ma przycisków).
  const chosenInStructure = (structure.data?.people ?? []).filter((person) =>
    selected.has(person.user_id),
  );
  const structureWords = managerWords(chosenInStructure.map((person) => person.employment_type));
  const candidates = (structure.data?.people ?? []).map((person) => ({
    user_id: person.user_id,
    name: person.name,
  }));
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
  const toggleStatus = (value: StatusFilter) =>
    update({ status: statusFilter === value ? null : value });
  const closeBulkDialog = () => setBulkDialog(null);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative w-full max-w-[300px]">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            aria-label="Szukaj osoby"
            placeholder="Imię, stanowisko, koordynator"
            value={query}
            onChange={(event) => update({ q: event.target.value })}
            className="pl-8"
          />
        </div>
        <div role="group" aria-label="Filtry katalogu" className="flex flex-1 flex-wrap items-center gap-1.5">
          <FilterChip
            active={department === null}
            count={searched.length}
            onClick={() => update({ department: null })}
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
                    update({ department: department === group.department ? null : group.department })
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
              onClick={() => update({ form: form === item.value ? null : item.value })}
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
        {viewSwitch}
      </div>

      {selectable && selected.size > 0 ? (
        <div
          role="region"
          aria-label="Zaznaczone osoby"
          className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm"
        >
          <span className="font-medium text-foreground">
            Zaznaczono: {countPl(selected.size, "osoba", "osoby", "osób")}
          </span>
          {canBulk ? (
            <>
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
            </>
          ) : null}
          {canStructure && chosenInStructure.length > 0 ? (
            <>
              {canBulk ? <span aria-hidden className="mx-1 h-5 w-px bg-border" /> : null}
              <Button
                size="sm"
                variant="outline"
                onClick={() => setBulkDialog({ kind: "division", people: chosenInStructure })}
              >
                Ustaw pion ({chosenInStructure.length})
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setBulkDialog({ kind: "reassign", people: chosenInStructure })}
              >
                Zmień {structureWords.ofOne} ({chosenInStructure.length})
              </Button>
            </>
          ) : null}
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
          {config.me.people_admin
            ? "Nikt nie ma jeszcze kartoteki. Dodaj osoby albo zaimportuj je z Compassa (Ustawienia → Import z Compassa)."
            : "Kartoteki nie zostały jeszcze założone."}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[960px]">
            <TableHeader>
              <TableRow>
                {selectable ? (
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
                <TableHead className={CALM_HEAD}>Koordynator</TableHead>
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
                      selectable={selectable}
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

      {bulkDialog?.kind === "reassign" ? (
        <ReassignDialog
          people={bulkDialog.people}
          candidates={candidates}
          open
          onOpenChange={(value) => (value ? null : closeBulkDialog())}
          onDone={() => setSelected(new Set())}
        />
      ) : null}
      {bulkDialog?.kind === "division" ? (
        <DivisionDialog
          people={bulkDialog.people}
          open
          onOpenChange={(value) => (value ? null : closeBulkDialog())}
          onDone={() => setSelected(new Set())}
        />
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
  selectable,
  selected,
  onSelect,
}: {
  row: Person;
  today: string;
  todayKnown: boolean;
  showForm: boolean;
  canBulk: boolean;
  selectable: boolean;
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
      {selectable ? (
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
          <span className="text-xs text-warning-muted-foreground">koordynator do uzupełnienia</span>
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
              chip.label === "dostępny(a)" ? (
                <span key={chip.label} className="inline-flex items-center gap-1.5 text-sm">
                  <span aria-hidden className="h-2 w-2 rounded-full bg-success" />
                  dostępny(a)
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
