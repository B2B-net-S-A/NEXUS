"use client";

import { Download } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile, type PersonFull } from "@/lib/api/hr";
import {
  TIMESHEET_STATUS_LABELS,
  timePaths,
  useMyMonth,
  useMyTimesheetHistory,
  type TimesheetHistoryItem,
} from "@/lib/api/hr-time";
import { employmentTerms } from "@/lib/hr-employment-terms";
import { countPl } from "@/lib/plural-pl";
import { monthTitlePl } from "@/lib/date-pl";

import { shortName } from "../../leave/leave-format";
import { currentYearMonth, hoursLabel, statusLine } from "../../time/time-format";
import {
  MANDATE_HOURS_NOTE,
  compactDays,
  missingDaysUntil,
  timesheetCardTitle,
} from "../overview-format";
import { Loading, OverviewCard, PartError, stateOf } from "./OverviewCard";

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
  form: PersonFull["employment_type"];
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
  const missingLine =
    missing.length > 0
      ? `${countPl(missing.length, "dzień", "dni", "dni")} do uzupełnienia: ${compactDays(missing)}`
      : "Dni do dziś uzupełnione";
  const reviewer = view.approver_name ? shortName(view.approver_name) : "Kadry";
  // Raport przyjmuje przełożony („akceptuje”) albo koordynator („potwierdza”) — D4.
  const progress = timesheetRequired
    ? `${missingLine} · ${words.review_verb} ${reviewer}`
    : `Bez obowiązku ${words.timesheet_genitive}`;
  const previous =
    history.isSuccess && history.data ? previousTimesheet(history.data, current) : null;
  return (
    <OverviewCard title={title} aside={timesheetRequired ? statusLine(view) : undefined}>
      <p className="text-lg font-semibold tabular-nums text-foreground">{hoursLabel(view.totals)}</p>
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
