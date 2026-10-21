"use client";

import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Download, FileSpreadsheet } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { daysLabel } from "@/components/hr/leave/leave-format";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile, type HrConfig } from "@/lib/api/hr";
import {
  TIMESHEET_STATUS_LABELS,
  reminderToast,
  timePaths,
  useDecideTimesheet,
  useRemindTimesheet,
  useTeamQueue,
  type TeamQueueItem,
} from "@/lib/api/hr-time";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { monthTitlePl, shiftMonth, type YearMonth, formatIsoDatePl } from "@/lib/date-pl";

import { TimesheetCsvDialog } from "./TimesheetCsvDialog";
import { TimesheetPreviewDialog } from "./TimesheetPreviewDialog";
import { useUrlMonth } from "./use-url-month";
import {
  QUEUE_COLLAPSED_ROWS,
  STATUS_TONE,
  canRemindInQueue,
  defaultQueueMonth,
  formatHours,
  queueHoursFill,
  queueHoursLabel,
  sortQueue,
} from "./time-format";

export interface TimesheetApprovalsSectionProps {
  config: HrConfig;
  /** Miesiąc z adresu (link z powiadomienia); domyślnie poprzedni do 10. dnia. */
  initialMonth?: YearMonth;
  /** Osoba do otwarcia w podglądzie (parametr `user` z linku powiadomienia). */
  focusUserId?: number | null;
}

/** Sekcja kolejki „Akceptacje”: timesheety zespołu za miesiąc. */
export function TimesheetApprovalsSection({
  config,
  initialMonth,
  focusUserId,
}: TimesheetApprovalsSectionProps) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [period, setPeriod] = useUrlMonth(initialMonth, defaultQueueMonth);
  const [previewId, setPreviewId] = useState<number | null>(focusUserId ?? null);
  // Osoba z linku powiadomienia przy otwartym ekranie (miękka nawigacja).
  useEffect(() => {
    if (focusUserId != null) setPreviewId(focusUserId);
  }, [focusUserId]);
  const [returning, setReturning] = useState<TeamQueueItem | null>(null);
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const canApprove =
    config.me.is_admin ||
    config.me.people_admin ||
    config.me.is_manager ||
    (config.me.covering?.length ?? 0) > 0;
  const canZip = config.me.is_admin || config.me.people_admin || config.me.payroll;
  const queue = useTeamQueue(period.year, period.month, config.open_modules.time && canApprove);
  const decide = useDecideTimesheet();
  const remind = useRemindTimesheet();

  if (!canApprove && !canZip) return null;

  const items = queue.data?.items ?? [];
  const state = resolveViewState({
    isLoading: queue.isLoading,
    isError: queue.isError,
    error: queue.error,
    isSuccess: queue.isSuccess,
    isEmpty: items.length === 0,
  });
  const previewed = items.find((item) => item.user_id === previewId) ?? null;
  const norm = queue.data?.norm_hours ?? null;
  const rows = sortQueue(items);
  const visibleRows = showAll ? rows : rows.slice(0, QUEUE_COLLAPSED_ROWS);

  const approve = async (item: TeamQueueItem) => {
    if (!item.timesheet) return;
    const ok = await askConfirm({
      title: `Zaakceptować timesheet: ${item.name}?`,
      description: `${monthTitlePl(period)} · ${formatHours(item.hours)} h${
        // Ekran wielu osób: neutralnie „ponad 8 h dziennie”, nie „nadgodziny” (21.10.2026).
        item.overtime_hours > 0 ? `, w tym ${formatHours(item.overtime_hours)} h ponad 8 h dziennie` : ""
      }. Po akceptacji powstaje PDF z sumą kontrolną.`,
      confirmLabel: "Akceptuj",
    });
    if (!ok) return;
    decide.mutate(
      { id: item.timesheet.id, decision: "approve" },
      {
        onSuccess: () => {
          showToast("Timesheet zaakceptowany", "success");
          setPreviewId(null);
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zaakceptować."), "error"),
      },
    );
  };

  const revoke = async (item: TeamQueueItem) => {
    if (!item.timesheet) return;
    const ok = await askConfirm({
      title: "Cofnąć akceptację?",
      description: `${item.name}, ${monthTitlePl(period).toLowerCase()}: timesheet wróci do akceptacji, a Płace dostaną powiadomienie.`,
      confirmLabel: "Cofnij akceptację",
      variant: "destructive",
    });
    if (!ok) return;
    decide.mutate(
      { id: item.timesheet.id, decision: "revoke" },
      {
        onSuccess: () => showToast("Akceptacja cofnięta", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się cofnąć akceptacji."), "error"),
      },
    );
  };

  const sendBack = () => {
    if (!returning?.timesheet) return;
    if (!note.trim()) {
      setNoteError("Napisz, co trzeba poprawić.");
      return;
    }
    decide.mutate(
      { id: returning.timesheet.id, decision: "return", note: note.trim() },
      {
        onSuccess: () => {
          showToast("Timesheet zwrócony do poprawy", "success");
          setReturning(null);
          setPreviewId(null);
          setNote("");
        },
        onError: (err) => setNoteError(apiErrorMessage(err, "Nie udało się zwrócić timesheetu.")),
      },
    );
  };

  const remindPerson = (item: TeamQueueItem) =>
    remind.mutate(
      { userId: item.user_id, year: period.year, month: period.month },
      {
        onSuccess: (result) =>
          showToast(reminderToast(result, item.name), result.already_today ? "info" : "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wysłać przypomnienia."), "error"),
      },
    );

  const remindButton = (item: TeamQueueItem, size: "sm" | "md" = "sm") =>
    canRemindInQueue(item) ? (
      <Button
        variant="outline"
        size={size}
        onClick={() => remindPerson(item)}
        disabled={remind.isPending && remind.variables?.userId === item.user_id}
      >
        Przypomnij
      </Button>
    ) : null;

  const downloadZip = async () => {
    try {
      await downloadHrFile(
        timePaths.monthZip(period.year, period.month),
        `timesheety-${period.year}-${String(period.month).padStart(2, "0")}.zip`,
      );
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać paczki PDF."), "error");
    }
  };

  const decisionButtons = (item: TeamQueueItem, size: "sm" | "md" = "sm") => {
    if (!item.can_decide || !item.timesheet || item.timesheet.payroll_locked) return null;
    if (item.status === "submitted") {
      return (
        <>
          <Button variant="ghost" size={size} onClick={() => setReturning(item)}>
            Zwróć
          </Button>
          <Button size={size} onClick={() => approve(item)} disabled={decide.isPending}>
            Akceptuj
          </Button>
        </>
      );
    }
    if (item.status === "approved") {
      return (
        <Button variant="quiet" size={size} onClick={() => revoke(item)} disabled={decide.isPending}>
          Cofnij akceptację
        </Button>
      );
    }
    return null;
  };

  return (
    <section aria-labelledby="timesheet-approvals-title" className="space-y-3" data-help="hr.approvals.timesheets">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <h2 id="timesheet-approvals-title" className="mr-2 text-base font-semibold text-foreground">
            Timesheety
          </h2>
          <Button variant="ghost" size="icon-sm" aria-label="Poprzedni miesiąc" onClick={() => setPeriod((p) => shiftMonth(p, -1))}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </Button>
          <span className="min-w-[8.5rem] text-center text-sm font-medium">{monthTitlePl(period)}</span>
          <Button variant="ghost" size="icon-sm" aria-label="Następny miesiąc" onClick={() => setPeriod((p) => shiftMonth(p, 1))}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {/* CSV godzin (jak Compass): osoba z kolejki za zakres miesięcy, a Płace
              i Kadry także cały zespół za miesiąc. */}
          <Button variant="ghost" size="sm" onClick={() => setExporting(true)}>
            <FileSpreadsheet className="mr-1.5 h-4 w-4" aria-hidden />
            Eksport CSV
          </Button>
          {canZip ? (
            <Button variant="outline" size="sm" onClick={downloadZip}>
              <Download className="mr-1.5 h-4 w-4" aria-hidden />
              Pobierz ZIP
            </Button>
          ) : null}
        </div>
      </div>

      {!canApprove ? null : state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie zespołu…</p>
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">
          W {monthTitlePl(period).toLowerCase()} nikt z Twojego zespołu nie prowadzi timesheetu.
        </p>
      ) : state !== "ready" ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => queue.refetch()}
        />
      ) : (
        <div className="max-h-[calc(100dvh-20rem)] overflow-auto rounded-lg border border-border/60">
          <table className="w-full min-w-[680px] border-collapse text-sm">
            <thead className="sticky top-0 z-10 bg-card">
              <tr className="border-b border-border/60">
                <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Osoba</th>
                <th className={cn(CALM_HEAD, "px-2 py-2 text-left")}>Status</th>
                <th className={cn(CALM_HEAD, "px-2 py-2 text-right")}>Godziny</th>
                <th className={cn(CALM_HEAD, "px-2 py-2 text-right")}>Ponad 8 h</th>
                <th className={cn(CALM_HEAD, "px-2 py-2 text-right")}>Nieobecność</th>
                <th className="px-2 py-2">
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((item) => (
                <tr key={item.user_id} className={CALM_ROW} data-testid={`queue-${item.user_id}`}>
                  <td className="px-3 py-2">
                    <span className="font-medium text-foreground">{item.name}</span>
                    {item.job_title ? <span className={CALM_SUBLINE}>{item.job_title}</span> : null}
                  </td>
                  <td className="px-2 py-2">
                    <StatusDot
                      tone={STATUS_TONE[item.status]}
                      note={
                        item.timesheet?.submitted_at && item.status === "submitted"
                          ? `wysłany ${formatIsoDatePl(item.timesheet.submitted_at)}`
                          : item.timesheet?.payroll_locked
                            ? "zamknięty w płacach"
                            : undefined
                      }
                    >
                      {TIMESHEET_STATUS_LABELS[item.status]}
                    </StatusDot>
                  </td>
                  <td className={cn(CALM_AMOUNT, "px-2 py-2")}>
                    {item.status === "missing" ? (
                      <span className={CALM_EMPTY}>—</span>
                    ) : (
                      <span className="ml-auto flex w-28 flex-col items-end gap-1">
                        <span>{queueHoursLabel(item.hours, norm)}</span>
                        {norm ? (
                          <span aria-hidden className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                            <span
                              className={cn(
                                "block h-full rounded-full",
                                item.hours >= norm ? "bg-success" : "bg-primary",
                              )}
                              style={{ width: `${queueHoursFill(item.hours, norm)}%` }}
                            />
                          </span>
                        ) : null}
                      </span>
                    )}
                  </td>
                  <td className={cn(CALM_AMOUNT, "px-2 py-2")}>
                    {item.overtime_hours > 0 ? (
                      formatHours(item.overtime_hours)
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </td>
                  <td className={cn(CALM_AMOUNT, "px-2 py-2")}>
                    {item.absence_days > 0 ? (
                      daysLabel(item.absence_days)
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex items-center justify-end gap-1">
                      <Button variant="ghost" size="sm" onClick={() => setPreviewId(item.user_id)}>
                        Podgląd
                      </Button>
                      {remindButton(item)}
                      {decisionButtons(item)}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > QUEUE_COLLAPSED_ROWS ? (
            <div className="border-t border-border/60 px-3 py-1.5">
              <Button variant="tertiary" size="sm" onClick={() => setShowAll((open) => !open)}>
                {showAll ? "Zwiń" : `Pokaż wszystkie (${rows.length})`}
              </Button>
            </div>
          ) : null}
        </div>
      )}

      {previewed ? (
        <TimesheetPreviewDialog
          userId={previewed.user_id}
          name={previewed.name}
          period={period}
          open
          onOpenChange={(open) => !open && setPreviewId(null)}
          canEdit={previewed.can_decide}
          allowOvertime={config.me.is_admin || config.me.people_admin}
          actions={
            <>
              {remindButton(previewed, "md")}
              {decisionButtons(previewed, "md")}
            </>
          }
        />
      ) : null}

      {exporting ? (
        <TimesheetCsvDialog
          open
          onOpenChange={setExporting}
          period={period}
          mode={{
            kind: "team",
            people: items.map((item) => ({ user_id: item.user_id, name: item.name })),
            allowMonth: canZip,
          }}
        />
      ) : null}

      {returning ? (
        <AppModal
          open
          onOpenChange={(open) => {
            if (!open) {
              setReturning(null);
              setNote("");
              setNoteError(null);
            }
          }}
          title={`Zwróć do poprawy: ${returning.name}`}
          description="Osoba dostanie powiadomienie z tą notatką, poprawi wpisy i wyśle ponownie."
          footer={
            <>
              <Button
                variant="ghost"
                onClick={() => {
                  setReturning(null);
                  setNote("");
                  setNoteError(null);
                }}
              >
                Anuluj
              </Button>
              <Button onClick={sendBack} disabled={decide.isPending}>
                Zwróć
              </Button>
            </>
          }
        >
          <FormField label="Co trzeba poprawić" htmlFor="timesheet-return-note">
            <Textarea
              id="timesheet-return-note"
              rows={3}
              maxLength={2000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
          </FormField>
          {noteError ? (
            <p role="alert" className="mt-3 text-sm text-destructive">
              {noteError}
            </p>
          ) : null}
        </AppModal>
      ) : null}
      {confirmDialog}
    </section>
  );
}
