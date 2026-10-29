"use client";

import { useState } from "react";
import { CalendarPlus } from "lucide-react";

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
  type LeaveRequestRow,
} from "@/lib/api/hr-leave";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { employmentTerms, reportsAbsence } from "@/lib/hr-employment-terms";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

import { AbsenceCard } from "../me/cards/AbsenceCard";
import { LeaveRequestDialog } from "./LeaveRequestDialog";
import { MyProofsCell } from "./LeaveProofs";
import {
  sourceBadge,
  HALF_DAY_LABELS,
  LEAVE_STATUS_TONE,
  daysLabel,
  formatRange,
  leaveToast,
  statusLabel,
  canToggleForward,
  yearMonths,
} from "./leave-format";

/**
 * „Mój rok”: 12 miesięcy z moimi nieobecnościami (zatwierdzone i czekające).
 * Święta i dni wolne firmy czyta tylko trasa Kadr — tu ich nie ma.
 */
function MyYearCard({
  rows,
  year,
  today,
}: {
  rows: readonly LeaveRequestRow[];
  year: number;
  today: string;
}) {
  const months = yearMonths(rows, year, today);
  return (
    <section className="space-y-2 rounded-xl border border-border bg-card p-4" aria-labelledby="my-year-title">
      <div className="flex flex-wrap items-center gap-2">
        <h2
          id="my-year-title"
          className="flex-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
        >
          Mój rok {year}
        </h2>
        <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[11px] text-primary">zatwierdzone</span>
        <span className="rounded-full bg-warning-muted px-2 py-0.5 text-[11px] text-warning-muted-foreground">
          czeka
        </span>
      </div>
      <ol className="grid grid-cols-3 gap-1.5 sm:grid-cols-4 lg:grid-cols-6">
        {months.map((cell) => (
          <li
            key={cell.month}
            data-testid={`my-year-${cell.month}`}
            aria-current={cell.current ? "date" : undefined}
            className={cn(
              "min-h-12 rounded-lg border px-2 py-1.5",
              cell.current ? "border-primary" : "border-border",
              cell.past ? "bg-muted/40" : "bg-card",
            )}
          >
            <span className={cn("block text-[11px] font-semibold", cell.past ? "text-muted-foreground" : "text-foreground")}>
              {cell.label}
            </span>
            <span className="mt-0.5 flex flex-wrap gap-1">
              {cell.items.map((item) => (
                <span
                  key={item.id}
                  className={cn(
                    "rounded-full px-1.5 text-[10px]",
                    item.status === "approved"
                      ? "bg-primary/15 text-primary"
                      : "bg-warning-muted text-warning-muted-foreground",
                  )}
                >
                  {item.label}
                </span>
              ))}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * „Mój czas → Urlop / Przerwy / Nieobecności” (nazwa według formy, D4): saldo,
 * „Złóż wniosek” albo „Zgłoś przerwę”, moje wpisy z anulowaniem i kolizją
 * zgłoszoną przez koordynatora (D5), załączniki do wniosków (dołącz, pobierz,
 * usuń własny plik).
 */
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
  const form = balance.data?.employment_type;
  const words = employmentTerms(form);
  const report = reportsAbsence(form);

  const rows = requests.data ?? [];
  const state = resolveViewState({
    isLoading: requests.isLoading,
    isError: requests.isError,
    error: requests.error,
    isSuccess: requests.isSuccess,
    isEmpty: rows.length === 0,
  });

  const cancelRow = async (row: LeaveRequestRow) => {
    const reported = Boolean(row.is_report);
    const ok = await askConfirm({
      title: reported ? "Anulować zgłoszenie?" : "Anulować wniosek?",
      description: `${formatRange(row.start_date, row.end_date)} · ${row.leave_type_label}. ${
        reported ? "Koordynator" : "Przełożony"
      } i zastępca dostaną powiadomienie.`,
      confirmLabel: reported ? "Anuluj zgłoszenie" : "Anuluj wniosek",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    cancel.mutate(row.id, {
      onSuccess: (saved) =>
        showToast(...leaveToast(reported ? "Zgłoszenie anulowane" : "Wniosek anulowany", saved)),
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
        <span className="text-sm text-muted-foreground">
          {report ? "Moje zgłoszenia i płatne dni z umowy." : "Mój urlop, plan roku i wnioski."}
        </span>
        <Button className="ml-auto" data-help="hr.my_time.leave_submit" onClick={() => setDialogOpen(true)}>
          <CalendarPlus className="h-4 w-4" aria-hidden />
          {report ? words.submit_action : "Złóż wniosek"}
        </Button>
      </div>
      {/* Saldo tą samą kartą co „Przegląd” zamiast 7 liczb w rzędzie; obok rok (runda 2, 21.10.2026). */}
      <div className="grid gap-3 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)] lg:items-start">
        {form ? (
          <AbsenceCard form={form} year={year} today={today} />
        ) : (
          <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
            {balance.isError ? "Nie udało się pobrać salda." : "Liczę saldo…"}
          </p>
        )}
        <MyYearCard rows={rows} year={year} today={today} />
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
                ? "Wnioski składają osoby z kartoteką w NEXUSIE."
                : undefined
          }
          onRetry={() => requests.refetch()}
        />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          {report
            ? `Nie masz jeszcze zgłoszeń. „${words.submit_action}” policzy dni robocze i płatne dni z umowy.`
            : "Nie masz jeszcze wniosków. „Złóż wniosek” policzy dni robocze i pulę."}
        </div>
      ) : (
        <div className="relative overflow-x-auto rounded-lg border border-border bg-card" data-help="hr.my_time.leave_list">
          <Table density="compact" className="min-w-[880px]">
            <TableHeader>
              <TableRow>
                <TableHead className={CALM_HEAD}>Rodzaj</TableHead>
                <TableHead className={CALM_HEAD}>Termin</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Dni</TableHead>
                <TableHead className={CALM_HEAD}>Status</TableHead>
                <TableHead className={CALM_HEAD}>Zastępca</TableHead>
                {/* Zgłoszenia B2B i zlecenia nie potrzebują dokumentu (D5). */}
                {report ? null : <TableHead className={CALM_HEAD}>Załącznik</TableHead>}
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
                    {/* „Z Outlooka” — wniosek założony z własnej autoodpowiedzi osoby. */}
                    {row.source === "outlook_oof" || row.source === "on_behalf" ? (
                      <span className={CALM_SUBLINE}>{sourceBadge(row.source)}</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {formatRange(row.start_date, row.end_date)}
                    {row.half_day ? (
                      <span className={CALM_SUBLINE}>{HALF_DAY_LABELS[row.half_day]}</span>
                    ) : null}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-right tabular-nums">
                    {daysLabel(row.days_total)}
                    {Number(row.unpaid_days) > 0 ? (
                      <span className={CALM_SUBLINE}>
                        {row.is_report ? "bez wynagrodzenia" : "bezpłatnie"}{" "}
                        {daysLabel(row.unpaid_days)}
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
                      {statusLabel(row)}
                    </StatusDot>
                    {row.conflict && row.status === "approved" ? (
                      <span className={`${CALM_SUBLINE} text-warning-muted-foreground`}>
                        kolizja{row.conflict.by_name ? ` · ${row.conflict.by_name}` : ""}:{" "}
                        {row.conflict.note}
                      </span>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    {row.substitute_name ?? <span className={CALM_EMPTY}>—</span>}
                    {row.forward_mail_consent ? (
                      <span className={CALM_SUBLINE}>przekierowanie poczty</span>
                    ) : null}
                    {row.cpro_substitute_name ? (
                      <span className={CALM_SUBLINE}>Cpro: {row.cpro_substitute_name}</span>
                    ) : null}
                  </TableCell>
                  {report ? null : (
                    <TableCell>
                      <MyProofsCell row={row} />
                    </TableCell>
                  )}
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
        employmentType={form}
      />
      {confirmDialog}
    </div>
  );
}
