"use client";

import { useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { CalendarPlus } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { yearMonthFromParams } from "@/components/hr/MyTimeScreen";
import { TimesheetApprovalsSection } from "@/components/hr/time/TimesheetApprovalsSection";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import type { HrConfig } from "@/lib/api/hr";
import {
  useCancelTeamLeave,
  useDecideLeave,
  useLeaveHistory,
  useOnBehalfPeople,
  usePendingLeave,
  type LeaveRequestRow,
  type LeaveStatus,
  type PendingLeaveRow,
} from "@/lib/api/hr-leave";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";

import { LeaveRequestDialog } from "./LeaveRequestDialog";
import { RejectLeaveDialog } from "./RejectLeaveDialog";
import {
  HALF_DAY_LABELS,
  LEAVE_STATUS_LABELS,
  LEAVE_STATUS_TONE,
  daysLabel,
  formatRange,
  shortDate,
} from "./leave-format";

/** Zdania pod wnioskiem w kolejce — co akceptujący powinien wiedzieć. */
export function pendingDetails(row: PendingLeaveRow, viewerIsHr: boolean): string[] {
  const lines: string[] = [];
  lines.push(row.substitute_name ? `zastępca ${row.substitute_name}` : "bez zastępcy");
  for (const kind of row.work_by_kind) {
    lines.push(`${kind.label}: ${kind.count}`);
  }
  if (row.department_absent.length > 0) {
    const names = row.department_absent
      .map((other) => `${other.name} (${shortDate(other.start_date)}–${shortDate(other.end_date)})`)
      .join(", ");
    lines.push(`w tym czasie nieobecni też: ${names}`);
  }
  if (viewerIsHr && row.manager_name) lines.push(`przełożony: ${row.manager_name}`);
  return lines;
}

interface ApprovalSection {
  key: string;
  title: string;
  render: () => ReactNode;
}

function PendingLeaveList({ viewerIsHr }: { viewerIsHr: boolean }) {
  const pending = usePendingLeave();
  const decide = useDecideLeave();
  const { showToast } = useToast();
  const [rejecting, setRejecting] = useState<LeaveRequestRow | null>(null);
  const rows = pending.data ?? [];
  const state = resolveViewState({
    isLoading: pending.isLoading,
    isError: pending.isError,
    error: pending.error,
    isSuccess: pending.isSuccess,
    isEmpty: rows.length === 0,
  });

  if (state === "loading") {
    return <p className="py-4 text-sm text-muted-foreground">Wczytywanie wniosków…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return (
      <QueryStateNotice
        state={state}
        description={
          state === "forbidden" ? "Akceptacje widzą przełożeni i Kadry." : undefined
        }
        onRetry={() => pending.refetch()}
      />
    );
  }
  if (state === "empty") {
    return (
      <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Nic nie czeka na Twoją decyzję.
      </p>
    );
  }

  const approve = (row: PendingLeaveRow) =>
    decide.mutate(
      { id: row.id, decision: "approve" },
      {
        onSuccess: () => showToast("Wniosek zaakceptowany", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zaakceptować."), "error"),
      },
    );

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className="min-w-[820px]">
        <TableHeader>
          <TableRow>
            <TableHead className={CALM_HEAD}>Kto</TableHead>
            <TableHead className={CALM_HEAD}>Termin</TableHead>
            <TableHead className={CALM_HEAD}>Szczegóły</TableHead>
            <TableHead className={CALM_HEAD}>
              <span className="sr-only">Decyzja</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id} className={CALM_ROW}>
              <TableCell className="py-2 align-top">
                <span className="font-medium text-foreground">{row.user_name}</span>
                {row.department ? <span className={CALM_SUBLINE}>{row.department}</span> : null}
              </TableCell>
              <TableCell className="py-2 align-top whitespace-nowrap">
                {formatRange(row.start_date, row.end_date)} · {daysLabel(row.days_total)}
                <span className={CALM_SUBLINE}>
                  {row.leave_type_label}
                  {row.half_day ? `, ${HALF_DAY_LABELS[row.half_day]}` : ""}
                </span>
              </TableCell>
              <TableCell className="py-2 align-top">
                <span className="text-sm text-foreground">
                  {pendingDetails(row, viewerIsHr).join(" · ")}
                </span>
                {row.note ? <span className={CALM_SUBLINE}>„{row.note}”</span> : null}
              </TableCell>
              <TableCell className="py-2 align-top text-right">
                <div className="flex justify-end gap-1.5">
                  <Button size="sm" variant="quiet" onClick={() => setRejecting(row)}>
                    Odrzuć
                  </Button>
                  <Button size="sm" disabled={decide.isPending} onClick={() => approve(row)}>
                    Akceptuj
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <RejectLeaveDialog
        request={rejecting}
        onClose={(rejected) => {
          setRejecting(null);
          if (rejected) showToast("Wniosek odrzucony", "success");
        }}
      />
    </div>
  );
}

const STATUS_FILTERS: { value: LeaveStatus | "all"; label: string }[] = [
  { value: "all", label: "Wszystkie statusy" },
  { value: "pending", label: LEAVE_STATUS_LABELS.pending },
  { value: "approved", label: LEAVE_STATUS_LABELS.approved },
  { value: "rejected", label: LEAVE_STATUS_LABELS.rejected },
  { value: "cancelled", label: LEAVE_STATUS_LABELS.cancelled },
];

function LeaveHistory() {
  const [status, setStatus] = useState<LeaveStatus | "all">("all");
  const [person, setPerson] = useState("all");
  const people = useOnBehalfPeople();
  const history = useLeaveHistory({
    status: status === "all" ? null : status,
    user_id: person === "all" ? null : Number(person),
  });
  const cancel = useCancelTeamLeave();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const rows = history.data ?? [];
  const state = resolveViewState({
    isLoading: history.isLoading,
    isError: history.isError,
    error: history.error,
    isSuccess: history.isSuccess,
    isEmpty: rows.length === 0,
  });

  const cancelRow = async (row: LeaveRequestRow) => {
    const ok = await askConfirm({
      title: "Anulować nieobecność?",
      description: `${row.user_name ?? "Osoba"} · ${formatRange(row.start_date, row.end_date)}. Osoba i zastępca dostaną powiadomienie, a autoodpowiedź zostanie zdjęta.`,
      confirmLabel: "Anuluj nieobecność",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    cancel.mutate(row.id, {
      onSuccess: () => showToast("Nieobecność anulowana", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się anulować."), "error"),
    });
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-foreground">Historia</h2>
        <div className="ml-auto flex flex-wrap gap-2">
          <Select value={status} onValueChange={(value) => setStatus(value as LeaveStatus | "all")}>
            <SelectTrigger className="h-8 w-[200px]" aria-label="Status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={person} onValueChange={setPerson}>
            <SelectTrigger className="h-8 w-[220px]" aria-label="Osoba">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Wszystkie osoby</SelectItem>
              {(people.data ?? []).map((row) => (
                <SelectItem key={row.user_id} value={String(row.user_id)}>
                  {row.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {state === "loading" ? (
        <p className="py-4 text-sm text-muted-foreground">Wczytywanie historii…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => history.refetch()} />
      ) : state === "empty" ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          Brak wniosków dla tych filtrów.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[860px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Kto</TableHead>
                <TableHead className={CALM_HEAD}>Rodzaj</TableHead>
                <TableHead className={CALM_HEAD}>Termin</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Dni</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
                <TableHead className={CALM_HEAD}>
                  <span className="sr-only">Akcje</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id} className={`${CALM_ROW} h-[48px]`}>
                  <TableCell className="font-medium text-foreground">{row.user_name}</TableCell>
                  <TableCell>{row.leave_type_label}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatRange(row.start_date, row.end_date)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {daysLabel(row.days_total)}
                  </TableCell>
                  <TableCell>
                    <StatusDot
                      tone={LEAVE_STATUS_TONE[row.status]}
                      note={
                        row.decision_note ??
                        (row.decided_by_name ? `decyzja: ${row.decided_by_name}` : undefined)
                      }
                    >
                      {LEAVE_STATUS_LABELS[row.status]}
                    </StatusDot>
                  </TableCell>
                  <TableCell className="text-right">
                    {row.status === "pending" || row.status === "approved" ? (
                      <Button
                        size="sm"
                        variant="quiet"
                        disabled={cancel.isPending}
                        onClick={() => void cancelRow(row)}
                      >
                        Anuluj
                      </Button>
                    ) : (
                      <span className={CALM_EMPTY}>—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
      {confirmDialog}
    </div>
  );
}

/**
 * „Ludzie → Akceptacje”: kolejka decyzji przełożonego i Kadr. Sekcje kolejki
 * to lista — timesheety (moduł `time`, etap E2) dopiszą tu własną sekcję.
 */
export function ApprovalsScreen({ config }: { config: HrConfig }) {
  const params = useSearchParams();
  const pending = usePendingLeave(config.open_modules.leave);
  const [entering, setEntering] = useState(false);
  const viewerIsHr = config.me.people_admin || config.me.is_admin;

  const sections: ApprovalSection[] = [];
  if (config.open_modules.leave) {
    sections.push({
      key: "leave",
      title: "Urlopy i nieobecności",
      render: () => <PendingLeaveList viewerIsHr={viewerIsHr} />,
    });
  }
  const timesheetViewer =
    config.me.is_manager || config.me.people_admin || config.me.payroll || config.me.is_admin;
  if (config.open_modules.time && timesheetViewer) {
    const focusUser = Number(params.get("user"));
    const timesheets: ApprovalSection = {
      key: "timesheets",
      title: "Timesheety",
      render: () => (
        <TimesheetApprovalsSection
          config={config}
          initialMonth={yearMonthFromParams(params)}
          focusUserId={Number.isInteger(focusUser) && focusUser > 0 ? focusUser : null}
        />
      ),
    };
    // Link z powiadomienia o timesheecie otwiera kolejkę od timesheetów.
    if (params.get("kind") === "timesheet") sections.unshift(timesheets);
    else sections.push(timesheets);
  }

  const waiting = pending.data?.length ?? null;
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <InlineStats
          stats={[
            {
              id: "waiting",
              label: "czeka na decyzję",
              value: waiting === null ? "—" : waiting,
            },
            {
              id: "scope",
              label: viewerIsHr ? "zakres" : "mój zespół",
              value: viewerIsHr
                ? "wszyscy"
                : countPl(config.me.direct_reports, "osoba", "osoby", "osób"),
            },
          ]}
        />
        {config.open_modules.leave ? (
          <Button className="ml-auto" variant="secondary" onClick={() => setEntering(true)}>
            <CalendarPlus className="h-4 w-4" aria-hidden />
            Wpisz nieobecność za pracownika
          </Button>
        ) : null}
      </div>

      {sections.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Akceptacje ruszą po włączeniu modułu urlopów albo czasu pracy.
        </p>
      ) : (
        sections.map((section) => (
          <section key={section.key} className="space-y-2" aria-label={section.title}>
            <h2 className="text-sm font-semibold text-foreground">{section.title}</h2>
            {section.render()}
          </section>
        ))
      )}

      {config.open_modules.leave ? <LeaveHistory /> : null}

      <LeaveRequestDialog open={entering} onOpenChange={setEntering} mode="on_behalf" />
    </div>
  );
}
