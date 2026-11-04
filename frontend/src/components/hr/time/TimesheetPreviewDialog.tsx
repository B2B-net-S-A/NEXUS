"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { CancelLeaveDialog } from "@/components/hr/leave/CancelLeaveDialog";
import { EditLeaveDialog } from "@/components/hr/leave/EditLeaveDialog";
import { canEditRow, formatRange, leaveToast } from "@/components/hr/leave/leave-format";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useLeaveHistory, type LeaveRequestRow } from "@/lib/api/hr-leave";
import {
  useDeleteTeamEntry,
  useSaveTeamEntry,
  useTeamMemberMonth,
  type MonthDay,
  type TimesheetEntry,
} from "@/lib/api/hr-time";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";
import { monthTitlePl, type YearMonth } from "@/lib/date-pl";
import { employmentTerms } from "@/lib/hr-employment-terms";

import { EntryDialog } from "./EntryDialog";
import { LeaveLimitNotice, MonthGrid } from "./MonthGrid";
import {
  afterLeaveCancelNote,
  formatHours,
  isFirstLeaveDay,
  leaveTermForDay,
  overLeaveLimit,
} from "./time-format";
import { useLeaveLimitFix } from "./use-leave-limit-fix";

export interface TimesheetPreviewDialogProps {
  userId: number;
  name: string;
  period: YearMonth;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Akceptujący może poprawiać wpisy w szkicu i w wysłanym. */
  canEdit: boolean;
  /** Prawo do nadgodzin akceptującego (kartoteka albo Kadry). */
  allowOvertime: boolean;
  /** Przyciski decyzji w stopce (akceptuj / zwróć) — podaje sekcja. */
  actions?: React.ReactNode;
  /** Kadry albo admin: mogą cofnąć także zgłoszenie z B2B i zlecenia (D5). */
  viewerIsHr?: boolean;
  /** Patrzący ma kolejkę nieobecności (`me.leave_approver`). */
  leaveAccess?: boolean;
}

interface EditorState {
  day: MonthDay;
  entry: TimesheetEntry | null;
}

/** Podgląd miesiąca osoby z zespołu, z poprawą wpisów przez akceptującego. */
export function TimesheetPreviewDialog({
  userId,
  name,
  period,
  open,
  onOpenChange,
  canEdit,
  allowOvertime,
  actions,
  viewerIsHr = false,
  leaveAccess = false,
}: TimesheetPreviewDialogProps) {
  const month = useTeamMemberMonth(open ? userId : null, period.year, period.month);
  const save = useSaveTeamEntry(userId, period.year, period.month);
  const remove = useDeleteTeamEntry();
  const [editor, setEditor] = useState<EditorState | null>(null);
  const fixDay = useLeaveLimitFix(save, (day, entry) => setEditor({ day, entry }));
  const { showToast } = useToast();
  const canFixLeave = open && canEdit && leaveAccess;
  const history = useLeaveHistory({ status: null, user_id: userId }, canFixLeave);
  const [cancelling, setCancelling] = useState<LeaveRequestRow | null>(null);
  const [changing, setChanging] = useState<LeaveRequestRow | null>(null);
  const view = month.data;
  const status = view?.timesheet?.status ?? "draft";
  const editable =
    canEdit && !view?.timesheet?.payroll_locked && (status === "draft" || status === "submitted");
  const state = resolveViewState({
    isLoading: month.isLoading,
    isError: month.isError,
    error: month.error,
    isSuccess: month.isSuccess,
  });

  // Termin wpisany przez pomyłkę: cofnięcie i zmiana dat bez wychodzenia z raportu.
  const leaveAction = (day: MonthDay) => {
    const term = leaveTermForDay(history.data?.items ?? [], day.date);
    if (!view || !term || !canEditRow(term, viewerIsHr)) return null;
    if (!isFirstLeaveDay(view.days, term, day.date)) return null;
    return (
      <span className="flex flex-wrap items-center gap-1">
        <Button variant="quiet" size="sm" onClick={() => setCancelling(term)}>
          Cofnij {formatRange(term.start_date, term.end_date)}
        </Button>
        <Button variant="quiet" size="sm" onClick={() => setChanging(term)}>
          Zmień daty
        </Button>
      </span>
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="xl"
      title={`${name} · ${monthTitlePl(period)}`}
      description="Godziny i miejsce pracy z każdego dnia. Stawek tu nie ma."
      footer={
        <>
          <Button variant="ghost" className="mr-auto" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
          {actions}
        </>
      }
    >
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie miesiąca…</p>
      ) : state !== "ready" || !view ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          onRetry={() => month.refetch()}
        />
      ) : (
        <div className="space-y-3">
          <InlineStats
            id="timesheet-preview-stats"
            stats={[
              { id: "work", label: "praca", value: `${formatHours(view.totals.work_hours)} h` },
              {
                id: "leave",
                label: "urlop płatny",
                value: `${formatHours(view.totals.leave_paid_hours)} h`,
              },
              {
                id: "overtime",
                label: employmentTerms(view.employment_type).overtime_stat,
                value: `${formatHours(view.totals.overtime_hours)} h`,
              },
              { id: "absence", label: "dni nieobecności", value: formatHours(view.totals.leave_days) },
              { id: "missing", label: "dni bez wpisów", value: view.totals.days_missing },
            ]}
          />
          <LeaveLimitNotice
            days={view.days.filter(overLeaveLimit)}
            onFix={editable ? fixDay : undefined}
            busy={save.isPending}
          />
          <MonthGrid
            view={view}
            today={warsawToday()}
            editable={editable}
            onEntryClick={(day, entry) => setEditor({ day, entry })}
            leaveAction={canFixLeave ? leaveAction : undefined}
          />
        </div>
      )}
      {editor && view ? (
        <EntryDialog
          key={`${editor.day.date}-${editor.entry?.id ?? "new"}`}
          open
          onOpenChange={(next) => !next && setEditor(null)}
          day={editor.day}
          entry={editor.entry}
          allowOvertime={allowOvertime}
          noHoursLimit={view.no_hours_limit}
          form={view.employment_type}
          onSave={(payload) => save.mutateAsync(payload)}
          onDelete={(id) => remove.mutateAsync(id)}
        />
      ) : null}
      <CancelLeaveDialog
        request={cancelling}
        today={warsawToday()}
        note={afterLeaveCancelNote(status, view?.timesheet?.payroll_locked === true)}
        onClose={(saved) => {
          setCancelling(null);
          if (saved) showToast(...leaveToast("Nieobecność cofnięta", saved));
        }}
      />
      <EditLeaveDialog
        request={changing}
        onClose={(saved) => {
          setChanging(null);
          if (saved) showToast(...leaveToast("Termin zmieniony", saved));
        }}
      />
    </AppModal>
  );
}
