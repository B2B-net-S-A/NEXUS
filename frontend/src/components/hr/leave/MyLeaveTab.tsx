"use client";

import { useState } from "react";
import { CalendarPlus } from "lucide-react";

import { InlineStats, type InlineStat } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useCancelMyLeave,
  useLeaveBalance,
  useMyLeaveRequests,
  useSetForwardConsent,
  type LeaveBalance,
  type LeaveRequestRow,
} from "@/lib/api/hr-leave";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import { LeaveRequestDialog } from "./LeaveRequestDialog";
import {
  HALF_DAY_LABELS,
  LEAVE_STATUS_LABELS,
  LEAVE_STATUS_TONE,
  daysLabel,
  formatRange,
  warsawToday,
} from "./leave-format";

/** Liczby salda do nagłówka zakładki (czysta funkcja — test bez renderu). */
export function balanceStats(balance: LeaveBalance): InlineStat[] {
  const stats: InlineStat[] = [];
  if (balance.has_pool) {
    stats.push(
      {
        id: "remaining",
        label: `zostało w ${balance.year}`,
        value: daysLabel(balance.remaining_days ?? "0"),
      },
      {
        id: "pool",
        label: "pula z zaległym",
        value: daysLabel(
          Number(balance.entitlement_days ?? 0) + Number(balance.carried_over_days ?? 0),
        ),
        title: Number(balance.used_initial_days ?? 0)
          ? `W tym ${daysLabel(balance.used_initial_days ?? "0")} wykorzystane przed NEXUSEM.`
          : undefined,
      },
    );
  } else {
    stats.push({ id: "remaining", label: `pula ${balance.year}`, value: "bez puli" });
  }
  stats.push(
    { id: "approved", label: "zatwierdzone z puli", value: daysLabel(balance.approved_days) },
    { id: "pending", label: "czeka na akceptację", value: daysLabel(balance.pending_days) },
  );
  if (Number(balance.unpaid_days) > 0) {
    stats.push({ id: "unpaid", label: "bezpłatne", value: daysLabel(balance.unpaid_days) });
  }
  if (balance.on_demand_limit !== null) {
    stats.push({
      id: "on-demand",
      label: "na żądanie",
      value: `${Number(balance.on_demand_used ?? 0).toLocaleString("pl-PL")} / ${Number(
        balance.on_demand_limit,
      )}`,
    });
  }
  return stats;
}

/** Czy osoba może jeszcze przełączyć przekierowanie poczty przy wniosku. */
export function canToggleForward(row: LeaveRequestRow, today: string): boolean {
  return (
    row.substitute_user_id !== null &&
    (row.status === "pending" || row.status === "approved") &&
    row.end_date >= today
  );
}

/** „Mój czas → Urlopy”: saldo, „Złóż wniosek”, moje wnioski z anulowaniem. */
export function MyLeaveTab() {
  const today = warsawToday();
  const year = Number(today.slice(0, 4));
  const balance = useLeaveBalance(year);
  const requests = useMyLeaveRequests();
  const cancel = useCancelMyLeave();
  const consent = useSetForwardConsent();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [dialogOpen, setDialogOpen] = useState(false);

  const rows = requests.data ?? [];
  const state = resolveViewState({
    isLoading: requests.isLoading,
    isError: requests.isError,
    error: requests.error,
    isSuccess: requests.isSuccess,
    isEmpty: rows.length === 0,
  });

  const cancelRow = async (row: LeaveRequestRow) => {
    const ok = await askConfirm({
      title: "Anulować wniosek?",
      description: `${formatRange(row.start_date, row.end_date)} · ${row.leave_type_label}. Przełożony i zastępca dostaną powiadomienie.`,
      confirmLabel: "Anuluj wniosek",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    cancel.mutate(row.id, {
      onSuccess: () => showToast("Wniosek anulowany", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się anulować."), "error"),
    });
  };

  const toggleForward = (row: LeaveRequestRow) => {
    consent.mutate(
      { id: row.id, consent: !row.forward_mail_consent },
      {
        onSuccess: (saved) =>
          showToast(
            saved.forward_mail_consent
              ? "Poczta będzie przekierowana do zastępcy"
              : "Przekierowanie poczty wyłączone",
            "success",
          ),
        onError: (err) =>
          showToast(apiErrorMessage(err, "Nie udało się zmienić przekierowania."), "error"),
      },
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        {balance.data ? (
          <InlineStats stats={balanceStats(balance.data)} />
        ) : balance.isError ? (
          <span className="text-sm text-muted-foreground">Nie udało się pobrać salda.</span>
        ) : (
          <span className="text-sm text-muted-foreground">Liczę saldo…</span>
        )}
        <Button className="ml-auto" onClick={() => setDialogOpen(true)}>
          <CalendarPlus className="h-4 w-4" aria-hidden />
          Złóż wniosek
        </Button>
      </div>

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie wniosków…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice
          state={state}
          description={
            state === "not_found"
              ? "Moduł urlopów nie jest jeszcze włączony."
              : state === "forbidden"
                ? "Wnioski składają osoby z kartoteką pracownika."
                : undefined
          }
          onRetry={() => requests.refetch()}
        />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          Nie masz jeszcze wniosków. „Złóż wniosek” policzy dni robocze i pulę.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          <Table density="compact" className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Rodzaj</TableHead>
                <TableHead className={CALM_HEAD}>Termin</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Dni</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
                <TableHead className={CALM_HEAD}>Zastępca</TableHead>
                <TableHead className={CALM_HEAD}>
                  <span className="sr-only">Akcje</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id} className={`${CALM_ROW} h-[50px]`}>
                  <TableCell className="font-medium text-foreground">
                    {row.leave_type_label}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatRange(row.start_date, row.end_date)}
                    {row.half_day ? (
                      <span className={CALM_SUBLINE}>{HALF_DAY_LABELS[row.half_day]}</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {daysLabel(row.days_total)}
                    {Number(row.unpaid_days) > 0 ? (
                      <span className={CALM_SUBLINE}>
                        bezpłatnie {daysLabel(row.unpaid_days)}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <StatusDot
                      tone={LEAVE_STATUS_TONE[row.status]}
                      note={
                        row.status === "rejected" && row.decision_note
                          ? row.decision_note
                          : row.source === "on_behalf" && row.decided_by_name
                            ? `wpis: ${row.decided_by_name}`
                            : row.decided_by_name && row.status === "approved"
                              ? `akceptacja: ${row.decided_by_name}`
                              : undefined
                      }
                    >
                      {LEAVE_STATUS_LABELS[row.status]}
                    </StatusDot>
                  </TableCell>
                  <TableCell>
                    {row.substitute_name ?? <span className={CALM_EMPTY}>—</span>}
                    {row.forward_mail_consent ? (
                      <span className={CALM_SUBLINE}>przekierowanie poczty</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-1">
                      {canToggleForward(row, today) ? (
                        <Button
                          size="sm"
                          variant="quiet"
                          disabled={consent.isPending}
                          onClick={() => toggleForward(row)}
                        >
                          {row.forward_mail_consent ? "Wyłącz przekierowanie" : "Przekieruj pocztę"}
                        </Button>
                      ) : null}
                      {row.can_cancel ? (
                        <Button
                          size="sm"
                          variant="quiet"
                          disabled={cancel.isPending}
                          onClick={() => void cancelRow(row)}
                        >
                          Anuluj
                        </Button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <LeaveRequestDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode="self"
        allowedTypes={balance.data?.allowed_types}
      />
      {confirmDialog}
    </div>
  );
}
