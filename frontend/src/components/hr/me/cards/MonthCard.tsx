"use client";

import { Download } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile, type OwnProfile } from "@/lib/api/hr";
import {
  TIMESHEET_STATUS_LABELS,
  timePaths,
  useMyMonth,
  useMyTimesheetHistory,
  type MonthView,
  type TimesheetHistoryItem,
} from "@/lib/api/hr-time";
import { employmentTerms } from "@/lib/hr-employment-terms";
import { countPl } from "@/lib/plural-pl";
import { monthTitlePl } from "@/lib/date-pl";

import { cn } from "@/lib/utils";

import { shortName } from "../../leave/leave-format";
import { currentYearMonth, hoursLabel, statusLine } from "../../time/time-format";
import {
  MANDATE_HOURS_NOTE,
  missingDaysUntil,
  missingLine,
  monthCalendar,
  monthHoursPercent,
  timesheetCardTitle,
  type CalendarDayKind,
} from "../overview-format";
import { Loading, OverviewCard, PartError, stateOf } from "./OverviewCard";

const WEEKDAYS = ["pn", "wt", "śr", "cz", "pt", "so", "nd"] as const;

const DAY_TONE: Record<CalendarDayKind, string> = {
  filled: "bg-success-muted font-semibold text-success-muted-foreground",
  remote: "bg-info-muted font-semibold text-info-muted-foreground",
  leave: "bg-primary/15 font-semibold text-primary",
  missing: "border-[1.5px] border-warning bg-card font-bold text-warning-muted-foreground hover:bg-warning-muted",
  empty: "bg-muted/60 text-muted-foreground",
  future: "bg-muted/60 text-muted-foreground",
  off: "text-muted-foreground/70",
};

/** Mini-kalendarz miesiąca: brakujący dzień to przycisk „uzupełnij”. */
function MiniCalendar({
  view,
  today,
  timesheetRequired,
  onFill,
}: {
  view: MonthView;
  today: string;
  timesheetRequired: boolean;
  onFill: () => void;
}) {
  const calendar = monthCalendar(view, today, timesheetRequired);
  if (calendar.days.length === 0) return null;
  return (
    <div
      role="group"
      aria-label="Dni miesiąca"
      className="grid grid-cols-7 gap-[3px] text-center text-[11px]"
    >
      {WEEKDAYS.map((day) => (
        <span key={day} aria-hidden className="text-muted-foreground/70">
          {day}
        </span>
      ))}
      {Array.from({ length: calendar.offset }, (_, index) => (
        <span key={`blank-${index}`} aria-hidden />
      ))}
      {calendar.days.map((day) =>
        day.kind === "missing" ? (
          <button
            key={day.date}
            type="button"
            onClick={onFill}
            title={day.label}
            aria-label={day.label}
            className={cn("flex h-6 items-center justify-center rounded-[5px]", DAY_TONE.missing)}
          >
            {day.day}
          </button>
        ) : (
          <span
            key={day.date}
            title={day.label}
            aria-label={day.label}
            className={cn("flex h-6 items-center justify-center rounded-[5px]", DAY_TONE[day.kind])}
          >
            {day.day}
          </span>
        ),
      )}
    </div>
  );
}

function previousTimesheet(
  items: readonly TimesheetHistoryItem[],
  current: { year: number; month: number },
): TimesheetHistoryItem | null {
  return (
    items.find((item) => item.year * 12 + item.month < current.year * 12 + current.month) ?? null
  );
}

export function MonthCard({
  form,
  today,
  timesheetRequired,
  onOpenTab,
}: {
  form: OwnProfile["employment_type"];
  today: string;
  /** Bez obowiązku timesheetu nie ma dni „do uzupełnienia” ani terminu wysyłki (jak „Do zrobienia”). */
  timesheetRequired: boolean;
  onOpenTab: (value: string) => void;
}) {
  const current = currentYearMonth();
  const month = useMyMonth(current.year, current.month);
  const history = useMyTimesheetHistory();
  const { showToast } = useToast();
  const state = stateOf(month);
  const title = `${timesheetCardTitle(form)} · ${monthTitlePl(current).split(" ")[0]}`;
  const words = employmentTerms(form);

  const download = async (item: TimesheetHistoryItem) => {
    try {
      await downloadHrFile(
        timePaths.myPdf(item.year, item.month),
        `timesheet-${item.year}-${String(item.month).padStart(2, "0")}.pdf`,
      );
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać PDF."), "error");
    }
  };

  if (state === "loading") {
    return (
      <OverviewCard title={title}>
        <Loading />
      </OverviewCard>
    );
  }
  if (state !== "ready" || !month.data) {
    return (
      <OverviewCard title={title}>
        <PartError label="Nie udało się wczytać miesiąca." onRetry={() => month.refetch()} />
      </OverviewCard>
    );
  }
  const view = month.data;
  const missing = missingDaysUntil(view, today);
  const reviewer = view.approver_name ? shortName(view.approver_name) : "Kadry";
  const lack = timesheetRequired ? missingLine(missing, today) : null;
  // Raport przyjmuje przełożony („akceptuje”) albo koordynator („potwierdza”) — D4.
  const progress = !timesheetRequired
    ? `Bez obowiązku ${words.timesheet_genitive}`
    : `${missing.length > 0 ? `${countPl(missing.length, "dzień", "dni", "dni")} do uzupełnienia` : "Dni do dziś uzupełnione"} · ${words.review_verb} ${reviewer}`;
  const percent = monthHoursPercent(view.totals);
  const previous =
    history.isSuccess && history.data ? previousTimesheet(history.data, current) : null;
  return (
    <OverviewCard
      title={title}
      aside={
        timesheetRequired ? (
          <span className="rounded-full bg-muted px-2 py-0.5 font-medium text-foreground">
            {statusLine(view)}
          </span>
        ) : undefined
      }
    >
      <p className="text-lg font-semibold tabular-nums text-foreground">{hoursLabel(view.totals)}</p>
      <div
        role="progressbar"
        aria-label="Godziny miesiąca wobec normy"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full bg-primary" style={{ width: `${percent}%` }} />
      </div>
      <MiniCalendar
        view={view}
        today={today}
        timesheetRequired={timesheetRequired}
        onFill={() => onOpenTab("month")}
      />
      {lack ? (
        <p className="flex items-center justify-between gap-2 text-sm">
          <span className="text-warning-muted-foreground">{lack}</span>
          <button
            type="button"
            className="font-medium text-primary underline-offset-2 hover:underline"
            onClick={() => onOpenTab("month")}
          >
            Uzupełnij
          </button>
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">{progress}</p>
      {form === "zlecenie" ? <p className="text-xs text-muted-foreground">{MANDATE_HOURS_NOTE}</p> : null}
      <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <button
          type="button"
          className="font-medium text-primary underline-offset-2 hover:underline"
          onClick={() => onOpenTab("month")}
        >
          Archiwum timesheetów
        </button>
        {history.isError ? (
          <PartError label="Nie udało się wczytać archiwum." onRetry={() => history.refetch()} />
        ) : previous ? (
          <span className="inline-flex items-center gap-1">
            · {monthTitlePl(previous).split(" ")[0]}: {TIMESHEET_STATUS_LABELS[previous.status].toLowerCase()}
            {previous.status === "approved" ? (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-1.5"
                onClick={() => void download(previous)}
                aria-label={`Pobierz PDF ${monthTitlePl(previous).toLowerCase()}`}
              >
                <Download className="mr-1 h-3.5 w-3.5" aria-hidden />
                PDF
              </Button>
            ) : null}
          </span>
        ) : null}
      </div>
    </OverviewCard>
  );
}
