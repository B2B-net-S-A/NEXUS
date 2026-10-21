"use client";

import { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Download } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { countPl } from "@/lib/plural-pl";
import { downloadHrFile, type HrConfig, type WorkLocation } from "@/lib/api/hr";
import {
  timePaths,
  useCopyPrevious,
  useDayHint,
  useDeleteMyEntry,
  useFillMonth,
  useMyMonth,
  useMyTemplates,
  useSaveMyEntry,
  useSetAttendance,
  useSubmitMonth,
  type FillResult,
  type MonthDay,
  type TimesheetEntry,
} from "@/lib/api/hr-time";
import { capitalize, employmentTerms } from "@/lib/hr-employment-terms";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { monthTitlePl, shiftMonth, type YearMonth } from "@/lib/date-pl";

import { EntryDialog } from "./EntryDialog";
import { FillMonthDialog } from "./FillMonthDialog";
import { TemplatesDialog } from "./TemplatesDialog";
import { TimesheetArchive } from "./TimesheetArchive";
import { useUrlMonth } from "./use-url-month";
import { MonthGrid, type QuickEntryInput } from "./MonthGrid";
import {
  STATUS_TONE,
  canEditMonth,
  currentYearMonth,
  formatHours,
  queueHoursFill,
  statusLine,
} from "./time-format";

/** Opis, gdy osoba nie ma domyślnego opisu roli (jak serwer i „Wypełnij miesiąc”). */
const STANDARD_DESCRIPTION = "Praca standardowa";

export interface MyMonthTabProps {
  config: HrConfig;
  /** Miesiąc z adresu (np. link z powiadomienia); domyślnie bieżący. */
  initialMonth?: YearMonth;
  /** Zmiana miesiąca — do zapisania w adresie (`useUrlWriter`). */
  onMonthChange?: (value: YearMonth) => void;
}

interface EditorState {
  day: MonthDay;
  entry: TimesheetEntry | null;
}

/**
 * „Mój czas → Mój miesiąc”: obecność i godziny w jednej siatce dni. Nazwa
 * raportu i kto go przyjmuje mówią językiem umowy (D4): ewidencja czasu pracy
 * do akceptacji przełożonego, raport godzin albo potwierdzenie godzin (art. 8b)
 * do potwierdzenia przez koordynatora.
 */
export function MyMonthTab({ config, initialMonth, onMonthChange }: MyMonthTabProps) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [period, setPeriod] = useUrlMonth(initialMonth, currentYearMonth);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [pendingDay, setPendingDay] = useState<string | null>(null);
  const [filling, setFilling] = useState(false);
  const [managingTemplates, setManagingTemplates] = useState(false);
  const moduleOpen = config.open_modules.time;

  const month = useMyMonth(period.year, period.month, moduleOpen);
  const templates = useMyTemplates(moduleOpen);
  const hint = useDayHint(editor ? editor.day.date : null);
  const save = useSaveMyEntry(period.year, period.month);
  const remove = useDeleteMyEntry();
  const attendance = useSetAttendance();
  const fill = useFillMonth(period.year, period.month);
  const copy = useCopyPrevious(period.year, period.month);
  const submit = useSubmitMonth(period.year, period.month);
  const today = warsawToday();

  const state = resolveViewState({
    isLoading: month.isLoading,
    isError: month.isError,
    error: month.error,
    isSuccess: month.isSuccess,
  });

  const openMonth = (next: YearMonth) => {
    setPeriod(next);
    onMonthChange?.(next);
  };
  const go = (delta: number) => openMonth(shiftMonth(period, delta));

  if (!moduleOpen) {
    return (
      <p className="rounded-lg border border-border/60 p-5 text-sm text-muted-foreground">
        „Mój miesiąc” ruszy po włączeniu modułu czasu pracy — do tego czasu
        timesheet prowadzisz w dotychczasowym systemie.
      </p>
    );
  }

  const view = month.data;
  const editable = view ? canEditMonth(view) : false;
  const words = employmentTerms(view?.employment_type);
  const reviewNoun = words.review_noun;

  const changeLocation = (day: MonthDay, location: WorkLocation) => {
    setPendingDay(day.date);
    attendance.mutate(
      { day: day.date, status: "active", location },
      {
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zapisać miejsca pracy."), "error"),
        onSettled: () => setPendingDay(null),
      },
    );
  };

  const roleDefault = templates.data?.role_default ?? null;
  const defaultDescription = roleDefault?.description || STANDARD_DESCRIPTION;
  const quickSave = (day: MonthDay, input: QuickEntryInput) =>
    save
      .mutateAsync({
        work_date: day.date,
        hours: input.hours,
        description: input.description,
        project: roleDefault?.project ?? null,
      })
      .catch((err: unknown) => {
        showToast(apiErrorMessage(err, "Nie udało się zapisać wpisu."), "error");
        throw err;
      });

  const filled = (result: FillResult) => {
    const removed =
      result.removed > 0
        ? ` Usunięto ${countPl(result.removed, "wcześniejszy wpis", "wcześniejsze wpisy", "wcześniejszych wpisów")}.`
        : "";
    showToast(
      result.inserted > 0
        ? `Wpisano ${countPl(result.inserted, "dzień", "dni", "dni")} po ${formatHours(result.hours_per_day)} h: „${result.description}”.${removed}`
        : `Wszystkie dni robocze mają już wpisy.${removed}`,
      "success",
    );
  };

  const runCopy = () => {
    copy.mutate(undefined, {
      onSuccess: (result) =>
        showToast(
          result.source
            ? `Skopiowano opisy z ${monthTitlePl(result.source).toLowerCase()}: ${countPl(result.inserted, "dzień", "dni", "dni")}.`
            : "Nie ma jeszcze zaakceptowanego miesiąca do skopiowania.",
          result.source ? "success" : "info",
        ),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się skopiować opisów."), "error"),
    });
  };

  const runSubmit = async () => {
    if (!view) return;
    const missing = view.totals.days_missing;
    const after = `Po wysłaniu poprawki wprowadza ${words.coordinator} albo zwraca ${words.timesheet_accusative} do Ciebie.`;
    const ok = await askConfirm({
      title: `Wysłać ${words.timesheet_accusative} za ${monthTitlePl(period).toLowerCase()} do ${reviewNoun}?`,
      description:
        missing > 0 ? `${countPl(missing, "dzień roboczy nie ma", "dni robocze nie mają", "dni roboczych nie ma")} wpisów. ${after}` : after,
      confirmLabel: "Wyślij",
    });
    if (!ok) return;
    submit.mutate(undefined, {
      onSuccess: () => showToast(`${words.timesheet} — wysłano do ${reviewNoun}`, "success"),
      onError: (err) =>
        showToast(
          apiErrorMessage(err, `Nie udało się wysłać: ${words.timesheet_accusative}.`),
          "error",
        ),
    });
  };

  const downloadPdf = async () => {
    try {
      await downloadHrFile(
        timePaths.myPdf(period.year, period.month),
        `timesheet-${period.year}-${String(period.month).padStart(2, "0")}.pdf`,
      );
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać PDF."), "error");
    }
  };

  const status = view?.timesheet?.status ?? "draft";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* Zawija się na wąskim ekranie (360 px): status schodzi pod miesiąc. */}
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          <Button variant="ghost" size="icon-sm" aria-label="Poprzedni miesiąc" onClick={() => go(-1)}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </Button>
          <h2 className="min-w-[9.5rem] text-center text-base font-semibold text-foreground">
            {monthTitlePl(period)}
          </h2>
          <Button variant="ghost" size="icon-sm" aria-label="Następny miesiąc" onClick={() => go(1)}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
          {view ? (
            <StatusDot tone={STATUS_TONE[status]} className="ml-2">
              {statusLine(view)}
            </StatusDot>
          ) : null}
        </div>
        {view ? (
          <div className="flex flex-wrap items-center gap-1.5" data-help="hr.my_time.month_actions">
            {status === "approved" ? (
              <Button variant="outline" size="sm" onClick={downloadPdf}>
                <Download className="mr-1.5 h-4 w-4" aria-hidden />
                Pobierz PDF
              </Button>
            ) : null}
            {/* Rzadkie akcje w jednym menu; na wierzchu zostaje wpis dnia i wysyłka (makieta 21.10.2026). */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm">
                  Więcej
                  <ChevronDown className="ml-1 h-4 w-4" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setManagingTemplates(true)}>Szablony opisów</DropdownMenuItem>
                {editable ? (
                  <>
                    <DropdownMenuItem onSelect={runCopy} disabled={copy.isPending}>
                      Skopiuj opisy z poprzedniego
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setFilling(true)} disabled={fill.isPending}>
                      Wypełnij miesiąc…
                    </DropdownMenuItem>
                  </>
                ) : null}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : null}
      </div>

      {view?.timesheet?.return_note && status === "draft" ? (
        <p role="status" className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
          Zwrócony do poprawy: {view.timesheet.return_note}
        </p>
      ) : null}

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie miesiąca…</p>
      ) : state !== "ready" || !view ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => month.refetch()}
        />
      ) : (
        <>
          {editable && view.totals.days_missing > 0 ? (
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2">
              <p className="min-w-0 flex-1 text-sm text-foreground">
                <span className="font-semibold">
                  Brakuje {countPl(view.totals.days_missing, "dnia roboczego", "dni roboczych", "dni roboczych")}.
                </span>{" "}
                <span className="text-muted-foreground">
                  Wpisz dzień w wierszu albo wypełnij puste dni po 8 h opisem „{defaultDescription}” — wpisane
                  dni, urlopy i święta zostają.
                </span>
              </p>
              <Button size="sm" onClick={() => setFilling(true)} disabled={fill.isPending}>
                Wypełnij puste dni…
              </Button>
            </div>
          ) : null}
          <MonthGrid
            view={view}
            today={today}
            editable={editable}
            onEntryClick={(day, entry) => setEditor({ day, entry })}
            onLocationChange={changeLocation}
            locationPending={pendingDay}
            onQuickSave={quickSave}
            defaultDescription={defaultDescription}
          />
          {/* Suma miesiąca i wysyłka pod siatką — siatka przewija się sama, pasek zostaje na widoku. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border/60 bg-card px-3 py-2">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-sm font-semibold tabular-nums text-foreground">
                {formatHours(view.totals.work_hours)} / {view.totals.norm_hours} h
              </span>
              <span className="h-1.5 w-32 overflow-hidden rounded-full bg-muted" aria-hidden>
                <span
                  className="block h-full rounded-full bg-primary"
                  style={{ width: `${queueHoursFill(view.totals.work_hours, view.totals.norm_hours)}%` }}
                />
              </span>
              <span className="text-xs text-muted-foreground">
                {view.totals.days_missing > 0
                  ? `brakuje ${countPl(view.totals.days_missing, "dnia roboczego", "dni roboczych", "dni roboczych")}`
                  : "wszystkie dni robocze wpisane"}
                {view.totals.leave_paid_hours > 0
                  ? ` · ${view.employment_type === "uop" ? "urlop płatny" : "płatne dni z umowy"} ${formatHours(view.totals.leave_paid_hours)} h`
                  : ""}
                {view.totals.overtime_hours > 0
                  ? ` · ${words.overtime_stat} ${formatHours(view.totals.overtime_hours)} h`
                  : ""}
                {` · ${words.review_verb}: `}
              </span>
              <span
                className="text-xs text-foreground"
                title={capitalize(`${words.coordinator} przyjmuje ${words.timesheet_accusative}.`)}
              >
                {view.approver_name ?? "Kadry"}
              </span>
            </div>
            {editable ? (
              <Button size="sm" onClick={runSubmit} disabled={submit.isPending}>
                Wyślij do {reviewNoun}
              </Button>
            ) : null}
          </div>
        </>
      )}

      <TimesheetArchive
        period={period}
        onOpenMonth={(item) => openMonth({ year: item.year, month: item.month })}
      />

      {filling && view ? (
        <FillMonthDialog
          open
          onOpenChange={setFilling}
          period={period}
          templates={templates.data?.items ?? []}
          roleDefault={templates.data?.role_default ?? null}
          onFill={(payload) => fill.mutateAsync(payload)}
          onDone={filled}
          form={view.employment_type}
        />
      ) : null}
      {managingTemplates ? (
        <TemplatesDialog open onOpenChange={setManagingTemplates} />
      ) : null}

      {editor && view ? (
        <EntryDialog
          key={`${editor.day.date}-${editor.entry?.id ?? "new"}`}
          open
          onOpenChange={(open) => !open && setEditor(null)}
          day={editor.day}
          entry={editor.entry}
          allowOvertime={view.can_log_overtime}
          form={view.employment_type}
          templates={templates.data?.items}
          hint={{ text: hint.data?.text ?? null, loading: hint.isLoading }}
          onSave={(payload) => save.mutateAsync(payload)}
          onDelete={(id) => remove.mutateAsync(id)}
        />
      ) : null}
      {confirmDialog}
    </div>
  );
}
