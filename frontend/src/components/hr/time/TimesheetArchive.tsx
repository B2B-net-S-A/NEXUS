"use client";

import { useState } from "react";
import { ChevronDown, Download, FileSpreadsheet } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  TIMESHEET_STATUS_LABELS,
  timePaths,
  useMyTimesheetHistory,
  type TimesheetHistoryItem,
} from "@/lib/api/hr-time";
import { resolveViewState } from "@/lib/view-state";
import { monthTitlePl, type YearMonth } from "@/lib/date-pl";
import { downloadHrFile } from "@/lib/api/hr";

import { TimesheetCsvDialog } from "./TimesheetCsvDialog";
import { STATUS_TONE, currentYearMonth, formatHours } from "./time-format";

interface TimesheetArchiveProps {
  /** Otwarcie miesiąca w siatce „Mojego miesiąca”. */
  onOpenMonth?: (item: TimesheetHistoryItem) => void;
  defaultOpen?: boolean;
  /** Miesiąc otwarty w siatce — domyślny zakres eksportu CSV. */
  period?: YearMonth;
}

/**
 * Archiwum timesheetów w „Moim miesiącu”: ostatnie 12 miesięcy ze statusem,
 * sumą godzin i PDF zaakceptowanego (`GET /api/hr/time/me/history`).
 * Zwinięte domyślnie i pobierane dopiero po rozwinięciu (`defaultOpen` —
 * rozwinięte od razu, np. po przejściu z „Przeglądu”).
 */
export function TimesheetArchive({ onOpenMonth, defaultOpen = false, period }: TimesheetArchiveProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [exporting, setExporting] = useState(false);
  const history = useMyTimesheetHistory(open);
  const { showToast } = useToast();
  const items = history.data ?? [];
  const state = resolveViewState({
    isLoading: history.isLoading,
    isError: history.isError,
    error: history.error,
    isSuccess: history.isSuccess,
    isEmpty: items.length === 0,
  });

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

  return (
    <section className="rounded-lg border border-border/60 bg-card" data-help="hr.my_time.archive">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="timesheet-archive"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-medium text-foreground"
      >
        <ChevronDown
          className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${open ? "" : "-rotate-90"}`}
          aria-hidden
        />
        Archiwum timesheetów
        <span className="text-xs font-normal text-muted-foreground">ostatnie 12 miesięcy</span>
      </button>
      {open ? (
        <div id="timesheet-archive" className="border-t border-border/60 px-3 py-2">
          {/* Eksport CSV (jak „Mój timesheet CSV” w Compassie) — własne godziny za zakres miesięcy. */}
          <div className="flex justify-end pb-1">
            <Button variant="ghost" size="sm" onClick={() => setExporting(true)}>
              <FileSpreadsheet className="mr-1.5 h-4 w-4" aria-hidden />
              Eksport CSV
            </Button>
          </div>
          {state === "loading" ? (
            <p className="text-sm text-muted-foreground">Wczytywanie archiwum…</p>
          ) : state === "empty" ? (
            <p className="text-sm text-muted-foreground">Nie ma jeszcze żadnego timesheetu.</p>
          ) : state !== "ready" ? (
            <QueryStateNotice
              state={state === "forbidden" || state === "not_found" ? state : "error"}
              onRetry={() => history.refetch()}
            />
          ) : (
            <ul className="divide-y divide-border/60">
              {items.map((item) => (
                <li key={item.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
                  {onOpenMonth ? (
                    <button
                      type="button"
                      className="min-w-[9rem] text-left text-sm font-medium text-foreground hover:underline"
                      onClick={() => onOpenMonth(item)}
                    >
                      {monthTitlePl(item)}
                    </button>
                  ) : (
                    <span className="min-w-[9rem] text-sm font-medium text-foreground">
                      {monthTitlePl(item)}
                    </span>
                  )}
                  <StatusDot tone={STATUS_TONE[item.status]}>
                    {TIMESHEET_STATUS_LABELS[item.status].toLowerCase()}
                  </StatusDot>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {formatHours(item.hours)} h
                  </span>
                  {item.status === "approved" ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      onClick={() => void download(item)}
                      aria-label={`Pobierz PDF ${monthTitlePl(item).toLowerCase()}`}
                    >
                      <Download className="mr-1.5 h-4 w-4" aria-hidden />
                      PDF
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
      {exporting ? (
        <TimesheetCsvDialog
          open
          onOpenChange={setExporting}
          mode={{ kind: "self" }}
          period={period ?? currentYearMonth()}
        />
      ) : null}
    </section>
  );
}
