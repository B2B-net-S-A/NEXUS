"use client";

import { useState } from "react";
import Link from "next/link";
import { FileArchive, FileSpreadsheet, Lock, LockOpen, Plus } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { InlineStats, type InlineStat } from "@/components/ds/InlineStats";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
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
import type { HrConfig } from "@/lib/api/hr";
import {
  closeConflict,
  downloadPayrollFile,
  payrollPaths,
  useApproveBonus,
  useCancelBonus,
  useCloseMonth,
  usePayrollMonth,
  useReopenMonth,
  type BonusRow,
  type PayrollMonthDetail,
  type PayrollPerson,
} from "@/lib/api/hr-payroll";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";

import { BonusDialog } from "./BonusDialog";
import { BonusTable } from "./BonusTable";
import {
  EMPLOYMENT_LABELS,
  capitalize,
  formatDay,
  formatHours,
  formatMoney,
  formatTotals,
  timesheetLabel,
  timesheetTone,
  ymSegment,
} from "./payroll-format";

/** Liczby nad tabelą (czysta funkcja — test bez renderu). */
export function monthStats(detail: PayrollMonthDetail): InlineStat[] {
  const stats: InlineStat[] = [
    { id: "people", label: "osób", value: detail.stats.people },
    {
      id: "approved",
      label: "timesheetów zaakceptowanych",
      value: detail.stats.timesheets_approved,
    },
    { id: "submitted", label: "czeka na akceptację", value: detail.stats.timesheets_submitted },
    { id: "missing", label: "nie wysłanych", value: detail.stats.timesheets_missing },
    { id: "proposals", label: "premie do decyzji", value: detail.stats.proposals },
  ];
  if (detail.totals) {
    stats.push({
      id: "totals",
      label: "razem do wypłaty",
      value: formatTotals(detail.totals),
      title: "Liczone są tylko zaakceptowane godziny i przyznane premie.",
    });
  }
  return stats;
}

/** Premie podzielone na sekcje ekranu. */
export function splitBonuses(bonuses: BonusRow[]): {
  toDecide: BonusRow[];
  assigned: BonusRow[];
  cancelled: number;
} {
  return {
    toDecide: bonuses.filter((b) => b.status === "proposed"),
    assigned: bonuses.filter((b) => b.status === "assigned"),
    cancelled: bonuses.filter((b) => b.status === "cancelled").length,
  };
}

function Stacked({ values }: { values: string[] }) {
  if (values.length === 0) return <span className={CALM_EMPTY}>—</span>;
  return (
    <>
      {values.map((value, index) => (
        <span key={index} className="block">
          {value}
        </span>
      ))}
    </>
  );
}

export function PeopleTable({ people, scope }: { people: PayrollPerson[]; scope: "payroll" | "team" }) {
  const payroll = scope === "payroll";
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border bg-card">
      <Table density="compact" className={payroll ? "min-w-[980px]" : "min-w-[620px]"}>
        <TableHeader>
          <TableRow>
            <TableHead className={`${CALM_HEAD} sticky left-0 bg-card`}>Osoba</TableHead>
            {payroll ? <TableHead className={CALM_HEAD}>Forma</TableHead> : null}
            <TableHead className={`${CALM_HEAD} text-right`}>Godziny</TableHead>
            {payroll ? (
              <>
                <TableHead className={`${CALM_HEAD} text-right`}>Stawka /h</TableHead>
                <TableHead className={`${CALM_HEAD} text-right`}>Za godziny</TableHead>
              </>
            ) : null}
            <TableHead className={`${CALM_HEAD} text-right`}>Premie</TableHead>
            {payroll ? <TableHead className={`${CALM_HEAD} text-right`}>Razem</TableHead> : null}
            <TableHead className={CALM_HEAD}>Timesheet</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {people.map((person) => {
            const lines = person.lines ?? [];
            const bonuses = payroll
              ? lines.filter((l) => Number(l.bonus_total) > 0)
              : (person.bonuses ?? []);
            return (
              <TableRow key={person.user_id} className={CALM_ROW}>
                <TableCell className="sticky left-0 bg-card">
                  <Link
                    href={`/people/${person.user_id}`}
                    className="font-medium text-foreground hover:underline"
                  >
                    {person.name}
                  </Link>
                  {person.rate_missing ? (
                    <span className={CALM_SUBLINE}>brak stawki — godziny bez kwoty</span>
                  ) : null}
                </TableCell>
                {payroll ? (
                  <TableCell className="text-sm text-muted-foreground">
                    {EMPLOYMENT_LABELS[person.employment_type ?? ""] ?? "—"}
                  </TableCell>
                ) : null}
                <TableCell className={`${CALM_AMOUNT} text-sm`}>
                  {Number(person.hours) > 0 ? formatHours(person.hours) : <span className={CALM_EMPTY}>—</span>}
                  {Number(person.overtime_hours) > 0 ? (
                    <span className={CALM_SUBLINE}>
                      w tym {formatHours(person.overtime_hours)} ponad normę
                    </span>
                  ) : null}
                </TableCell>
                {payroll ? (
                  <>
                    <TableCell className={`${CALM_AMOUNT} text-sm`}>
                      <Stacked
                        values={lines
                          .filter((l) => l.hourly_rate !== null)
                          .map((l) => formatMoney(l.hourly_rate, l.currency))}
                      />
                    </TableCell>
                    <TableCell className={`${CALM_AMOUNT} text-sm`}>
                      <Stacked
                        values={lines
                          .filter((l) => l.hours_amount !== null)
                          .map((l) => formatMoney(l.hours_amount, l.currency))}
                      />
                    </TableCell>
                  </>
                ) : null}
                <TableCell className={`${CALM_AMOUNT} text-sm`}>
                  <Stacked values={bonuses.map((b) => formatMoney(b.bonus_total, b.currency))} />
                </TableCell>
                {payroll ? (
                  <TableCell className={`${CALM_AMOUNT} text-sm font-semibold text-foreground`}>
                    <Stacked
                      values={lines
                        .filter((l) => Number(l.total) !== 0)
                        .map((l) => formatMoney(l.total, l.currency))}
                    />
                  </TableCell>
                ) : null}
                <TableCell>
                  <StatusDot
                    tone={timesheetTone(person.timesheet_status, person.timesheet_required)}
                  >
                    {timesheetLabel(person.timesheet_status, person.timesheet_required)}
                  </StatusDot>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function ReopenDialog({
  open,
  onOpenChange,
  year,
  month,
  label,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  year: number;
  month: number;
  label: string;
}) {
  const { showToast } = useToast();
  const reopen = useReopenMonth(year, month);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    setError(null);
    if (reason.trim().length < 3) {
      setError("Podaj powód ponownego otwarcia.");
      return;
    }
    reopen.mutate(reason.trim(), {
      onSuccess: () => {
        showToast("Miesiąc otwarty ponownie", "success");
        onOpenChange(false);
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się otworzyć miesiąca.")),
    });
  };
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Otworzyć ponownie ${label}?`}
      description="Zamrożone kwoty znikną, raport znów policzy się z danych, a timesheety tego miesiąca zostaną odblokowane. Powód trafi do śladu zmian."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button variant="destructive" onClick={submit} disabled={reopen.isPending}>
            {reopen.isPending ? "Otwieranie…" : "Otwórz ponownie"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor="payroll-reopen-reason">
        <Input
          id="payroll-reopen-reason"
          value={reason}
          maxLength={1000}
          onChange={(event) => setReason(event.target.value)}
        />
      </FormField>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

/** „Ludzie → Płace → miesiąc”: osoby, premie do decyzji, eksport i zamknięcie. */
export function PayrollMonthScreen({
  config,
  year,
  month,
}: {
  config: HrConfig;
  year: number;
  month: number;
}) {
  const detail = usePayrollMonth(year, month);
  const close = useCloseMonth(year, month);
  const approve = useApproveBonus();
  const cancel = useCancelBonus();
  const me = useAuthStore((state) => state.user);
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [bonusOpen, setBonusOpen] = useState(false);
  const [editing, setEditing] = useState<BonusRow | null>(null);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [downloading, setDownloading] = useState<"xlsx" | "zip" | null>(null);

  const state = resolveViewState({
    isLoading: detail.isLoading,
    isError: detail.isError,
    error: detail.error,
    isSuccess: detail.isSuccess,
  });
  const data = detail.data;
  const label = data ? capitalize(data.label) : `${ymSegment(year, month)}`;

  const download = async (kind: "xlsx" | "zip") => {
    setDownloading(kind);
    try {
      if (kind === "xlsx") {
        await downloadPayrollFile(
          payrollPaths.export(year, month),
          `place-${ymSegment(year, month)}.xlsx`,
        );
      } else {
        await downloadPayrollFile(
          payrollPaths.timesheetsZip(year, month),
          `timesheety-${ymSegment(year, month)}.zip`,
        );
      }
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
    } finally {
      setDownloading(null);
    }
  };

  const closeMonth = async () => {
    const ok = await askConfirm({
      title: `Zamknąć ${data?.label ?? "miesiąc"}?`,
      description:
        "Kwoty zostaną zamrożone, a timesheety tego miesiąca zablokowane. Ponownie otworzyć miesiąc może tylko administrator.",
      confirmLabel: "Zamknij miesiąc",
      cancelLabel: "Wróć",
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await close.mutateAsync(false);
      showToast("Miesiąc zamknięty", "success");
    } catch (err) {
      const conflict = closeConflict(err);
      if (conflict?.code === "close_warnings") {
        const again = await askConfirm({
          title: "Zamknąć mimo ostrzeżeń?",
          description: conflict.warnings.map((w) => w.message).join(" "),
          confirmLabel: "Zamknij mimo to",
          cancelLabel: "Wróć",
          variant: "destructive",
        });
        if (!again) return;
        try {
          await close.mutateAsync(true);
          showToast("Miesiąc zamknięty", "success");
        } catch (second) {
          showToast(apiErrorMessage(second, "Nie udało się zamknąć miesiąca."), "error");
        }
        return;
      }
      showToast(apiErrorMessage(err, "Nie udało się zamknąć miesiąca."), "error");
    }
  };

  const approveRow = (row: BonusRow) =>
    approve.mutate(row.id, {
      onSuccess: () => showToast("Premia zatwierdzona", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zatwierdzić."), "error"),
    });

  const cancelRow = async (row: BonusRow) => {
    const proposal = row.status === "proposed";
    const ok = await askConfirm({
      title: proposal ? "Odrzucić propozycję premii?" : "Anulować premię?",
      description: `${row.recipient_name ?? "Osoba"} · ${formatMoney(row.amount, row.currency)}. ${
        proposal
          ? "Automat nie zaproponuje jej ponownie."
          : "Osoba dostanie powiadomienie o anulowaniu (bez kwoty)."
      }`,
      confirmLabel: proposal ? "Odrzuć" : "Anuluj premię",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    cancel.mutate(
      { id: row.id },
      {
        onSuccess: () => showToast(proposal ? "Propozycja odrzucona" : "Premia anulowana", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się anulować."), "error"),
      },
    );
  };

  if (state === "loading") {
    return <p className="p-6 text-sm text-muted-foreground">Wczytywanie miesiąca…</p>;
  }
  if (state !== "ready" || !data) {
    return (
      <div className="space-y-4">
        <PageHeader title={`Płace · ${label}`} density="compact" />
        <PeopleSectionNav config={config} active="payroll" />
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={
            state === "forbidden"
              ? "Miesiąc płac widzą Płace i przełożeni (godziny i premie swojego zespołu)."
              : state === "not_found"
                ? "Moduł Płac nie jest jeszcze włączony."
                : undefined
          }
          onRetry={() => detail.refetch()}
        />
      </div>
    );
  }

  const payroll = data.scope === "payroll";
  const open = data.status === "open";
  const { toDecide, assigned, cancelled } = splitBonuses(data.bonuses);
  const decidable = toDecide.filter((b) => b.eligible !== false);
  const people = data.people.map((p) => ({ user_id: p.user_id, name: p.name }));
  const mine = (row: BonusRow) => me?.id === row.recipient_user_id;
  const canEdit = (row: BonusRow) =>
    open && !mine(row) && (payroll || row.proposed_by === me?.id);

  return (
    <div className="space-y-4">
      <PageHeader
        title={`Płace · ${label}`}
        description={
          data.status === "closed"
            ? `Miesiąc zamknięty${data.closed_at ? ` ${formatDay(data.closed_at)}` : ""} — kwoty zamrożone.`
            : "Liczone są tylko zaakceptowane godziny i przyznane premie."
        }
        density="compact"
        actions={
          payroll ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => download("xlsx")}
                disabled={downloading !== null}
              >
                <FileSpreadsheet className="h-4 w-4" aria-hidden />
                {downloading === "xlsx" ? "Pobieranie…" : "Eksport do księgowości (XLSX)"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => download("zip")}
                disabled={downloading !== null || !config.open_modules.time}
                title={
                  config.open_modules.time
                    ? "Zaakceptowane timesheety miesiąca w jednym pliku."
                    : "Paczka PDF-ów ruszy po włączeniu modułu czasu pracy."
                }
              >
                <FileArchive className="h-4 w-4" aria-hidden />
                {downloading === "zip" ? "Pobieranie…" : "PDF-y timesheetów (ZIP)"}
              </Button>
              {data.can_close ? (
                <Button size="sm" onClick={closeMonth} disabled={close.isPending}>
                  <Lock className="h-4 w-4" aria-hidden />
                  {close.isPending ? "Zamykanie…" : "Zamknij miesiąc"}
                </Button>
              ) : null}
              {data.can_reopen ? (
                <Button variant="quiet" size="sm" onClick={() => setReopenOpen(true)}>
                  <LockOpen className="h-4 w-4" aria-hidden />
                  Otwórz ponownie
                </Button>
              ) : null}
            </div>
          ) : undefined
        }
      />
      <PeopleSectionNav config={config} active="payroll" />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <InlineStats id="payroll-month-stats" stats={monthStats(data)} />
        <div className="flex items-center gap-3">
          {payroll ? (
            <Link href="/people/payroll" className="text-sm text-primary hover:underline">
              Wszystkie miesiące
            </Link>
          ) : null}
          {open && people.length > 0 ? (
            <Button size="sm" variant="secondary" onClick={() => setBonusOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              Nowa premia
            </Button>
          ) : null}
        </div>
      </div>

      {payroll && open && (data.warnings ?? []).length > 0 ? (
        <div className="rounded-lg border border-border bg-muted/40 px-4 py-2 text-sm text-muted-foreground">
          Przed zamknięciem: {(data.warnings ?? []).map((w) => w.message).join(" ")}
        </div>
      ) : null}

      {data.people.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
          {payroll
            ? "W tym miesiącu nikt z kartoteką nie był zatrudniony."
            : "Nikt z Twojego zespołu nie ma w tym miesiącu godzin ani premii."}
        </div>
      ) : (
        <PeopleTable people={data.people} scope={data.scope} />
      )}

      {decidable.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
            Premie do decyzji
          </h2>
          <BonusTable
            rows={decidable}
            renderActions={(row) =>
              open && !mine(row) ? (
                <div className="flex justify-end gap-1">
                  <Button size="sm" onClick={() => approveRow(row)} disabled={approve.isPending}>
                    Zatwierdź
                  </Button>
                  {payroll ? (
                    <Button size="sm" variant="ghost" onClick={() => setEditing(row)}>
                      Zmień
                    </Button>
                  ) : null}
                  <Button size="sm" variant="quiet" onClick={() => cancelRow(row)}>
                    Odrzuć
                  </Button>
                </div>
              ) : null
            }
          />
        </section>
      ) : null}

      {data.in_progress.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
            Placementy — premie liczą się
          </h2>
          <BonusTable rows={data.in_progress} showProgress />
        </section>
      ) : null}

      <section className="space-y-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Premie przyznane w tym miesiącu
          {cancelled > 0 ? (
            <span className="ml-2 font-normal normal-case tracking-normal">
              · anulowane: {cancelled}
            </span>
          ) : null}
        </h2>
        {assigned.length === 0 ? (
          <p className="text-sm text-muted-foreground">Brak przyznanych premii.</p>
        ) : (
          <BonusTable
            rows={assigned}
            renderActions={(row) =>
              canEdit(row) ? (
                <div className="flex justify-end gap-1">
                  <Button size="sm" variant="ghost" onClick={() => setEditing(row)}>
                    Zmień
                  </Button>
                  <Button size="sm" variant="quiet" onClick={() => cancelRow(row)}>
                    Anuluj
                  </Button>
                </div>
              ) : null
            }
          />
        )}
      </section>

      {bonusOpen ? (
        <BonusDialog
          open={bonusOpen}
          onOpenChange={setBonusOpen}
          people={people.filter((p) => p.user_id !== me?.id)}
          defaultMonth={ymSegment(year, month)}
        />
      ) : null}
      {editing ? (
        <BonusDialog
          key={editing.id}
          open
          onOpenChange={(value) => {
            if (!value) setEditing(null);
          }}
          people={people}
          bonus={editing}
        />
      ) : null}
      {reopenOpen ? (
        <ReopenDialog
          open={reopenOpen}
          onOpenChange={setReopenOpen}
          year={year}
          month={month}
          label={data.label}
        />
      ) : null}
      {confirmDialog}
    </div>
  );
}
