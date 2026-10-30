"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ChevronLeft,
  ChevronRight,
  FileArchive,
  FileSpreadsheet,
  Lock,
  LockOpen,
  Plus,
} from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { PeopleSectionNav } from "@/components/hr/people/PeopleSectionNav";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile, type HrConfig } from "@/lib/api/hr";
import {
  closeConflict,
  payrollPaths,
  useApproveBonus,
  useCancelBonus,
  useCloseMonth,
  usePayrollMonth,
  type BonusRow,
  type PayrollPerson,
} from "@/lib/api/hr-payroll";
import {
  reminderToast,
  timePaths,
  useRemindTimesheet,
  type TimesheetReminderResult,
} from "@/lib/api/hr-time";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";
import { formatMoney } from "@/lib/money";
import { formatIsoDatePl, shiftMonth } from "@/lib/date-pl";
import { capitalize } from "@/lib/hr-employment-terms";
import { useUrlSyncedState, writeUrlParams } from "@/lib/url-selection";

import { BonusDialog } from "./BonusDialog";
import { BonusDeleteDialog } from "./BonusDeleteDialog";
import { SettlementImportDialog } from "./SettlementImportDialog";
import { BonusTable } from "./BonusTable";
import { CloseStepper, DecisionPanel, PayoutCard, PlacementsStrip } from "./PayrollCloseParts";
import { PayrollPeopleTable } from "./PayrollPeopleTable";
import { SymfoniaExportButton } from "./payments/SymfoniaExportButton";
import { ReopenMonthDialog } from "./ReopenMonthDialog";
import {
  assignedBonusActions,
  bonusDecision,
  closeSteps,
  decidableBonuses,
  monthStats,
  reminderAction,
  splitBonuses,
  warsawMonth,
  ymSegment,
} from "./payroll-format";
import { MONTH_VIEW, PAYROLL_MONTH_TABS, payrollMonthTabs } from "./payroll-month-tabs";

/**
 * „Ludzie → Płace → miesiąc”: osoby, premie do decyzji, eksport i zamknięcie.
 * Płace mają zakładki modułów etapu 4 (`?view=settlements` — „Rozliczenia”,
 * `payroll-month-tabs.tsx`); przełożony widzi sam miesiąc swojego zespołu.
 */
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
  const [importOpen, setImportOpen] = useState(false);
  const [deleting, setDeleting] = useState<BonusRow | null>(null);
  const [editing, setEditing] = useState<BonusRow | null>(null);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [downloading, setDownloading] = useState<"xlsx" | "zip" | null>(null);
  // Krok „Kontrola”: ostrzeżenia potwierdzone na ekranie (zamknięcie idzie z
  // `acknowledge_warnings`). Potwierdzenie dotyczy TEGO zestawu ostrzeżeń —
  // nowe ostrzeżenie po kliknięciu (cofnięty timesheet, osoba bez stawki)
  // unieważnia je, a serwer zapyta o nie ponownie (audyt 21.10.2026).
  const [acknowledgedWarnings, setAcknowledgedWarnings] = useState<string | null>(null);
  const [assignedOpen, setAssignedOpen] = useState(false);
  const remind = useRemindTimesheet();
  const params = useSearchParams();
  const [view, setView] = useUrlSyncedState<string>(params.get("view"), MONTH_VIEW);

  const state = resolveViewState({
    isLoading: detail.isLoading,
    isError: detail.isError,
    error: detail.error,
    isSuccess: detail.isSuccess,
  });
  const data = detail.data;
  const label = data ? capitalize(data.label) : `${ymSegment(year, month)}`;
  const warningsKey = JSON.stringify((data?.warnings ?? []).map((w) => [w.code, w.message]));
  const acknowledged = acknowledgedWarnings !== null && acknowledgedWarnings === warningsKey;

  const download = async (kind: "xlsx" | "zip") => {
    setDownloading(kind);
    try {
      await downloadHrFile(
        kind === "xlsx" ? payrollPaths.export(year, month) : timePaths.monthZip(year, month),
        `${kind === "xlsx" ? "place" : "timesheety"}-${ymSegment(year, month)}.${kind}`,
      );
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
    } finally {
      setDownloading(null);
    }
  };

  const closeMonth = async () => {
    const ok = await askConfirm({
      title: `Zamknąć ${data?.label ?? "miesiąc"}?`,
      description: `Kwoty zostaną zamrożone, a timesheety tego miesiąca zablokowane.${
        acknowledged ? " Ostrzeżenia z kroku „Kontrola” są potwierdzone." : ""
      } Ponownie otworzyć miesiąc może tylko administrator.`,
      confirmLabel: "Zamknij miesiąc",
      cancelLabel: "Wróć",
      variant: "destructive",
    });
    if (!ok) return;
    try {
      await close.mutateAsync(acknowledged);
      showToast("Miesiąc zamknięty", "success");
    } catch (err) {
      const conflict = closeConflict(err);
      if (conflict?.code === "close_warnings") {
        // Nowe ostrzeżenie od ostatniego odczytu — pokazujemy je jeszcze raz.
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

  const remindPerson = (person: PayrollPerson) =>
    remind.mutate(
      { userId: person.user_id, year, month },
      {
        onSuccess: (result: TimesheetReminderResult) =>
          showToast(reminderToast(result, person.name), result.already_today ? "info" : "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wysłać przypomnienia."), "error"),
      },
    );

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
          ? row.source === "manual"
            ? "Propozycja zniknie z decyzji Płac."
            : "Automat nie zaproponuje jej ponownie."
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
              ? "Miesiąc płac widzą Płace i koordynatorzy (godziny i premie swojego zespołu)."
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
  const { assigned, cancelled } = splitBonuses(data.bonuses);
  const decidable = decidableBonuses(data.bonuses);
  const steps = closeSteps(data, acknowledged);
  const prev = shiftMonth({ year, month }, -1);
  const next = shiftMonth({ year, month }, 1);
  const hasNext = ymSegment(next.year, next.month) <= warsawMonth();
  const people = data.people.map((p) => ({ user_id: p.user_id, name: p.name }));
  const tabs = payrollMonthTabs(config, payroll);
  const activeView = tabs.some((tab) => tab.value === view) ? view : MONTH_VIEW;
  const moduleTab = PAYROLL_MONTH_TABS.find((tab) => tab.value === activeView);
  const changeView = (value: string) => {
    setView(value);
    writeUrlParams({ view: value === MONTH_VIEW ? null : value, settlement: null });
  };
  const mine = (row: BonusRow) => me?.id === row.recipient_user_id;

  return (
    <div className="space-y-4">
      <PageHeader
        title={`Płace · ${label}`}
        description={
          data.status === "closed"
            ? `Miesiąc zamknięty${data.closed_at ? ` ${formatIsoDatePl(data.closed_at)}` : ""} — kwoty zamrożone.`
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
              {config.open_modules.settlements ? (
                <SymfoniaExportButton year={year} month={month} closed={data.status === "closed"} />
              ) : null}
              {open ? (
                <Button
                  size="sm"
                  onClick={closeMonth}
                  disabled={!steps.ready || close.isPending}
                  title={steps.ready ? undefined : `Zamknięcie ${steps.steps[3].detail}.`}
                >
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
      {tabs.length > 0 ? (
        <TabbedNav
          ariaLabel="Miesiąc płac"
          overflow="scroll"
          tabs={tabs}
          value={activeView ?? MONTH_VIEW}
          onValueChange={changeView}
        />
      ) : null}

      {moduleTab ? (
        moduleTab.render({ config, year, month })
      ) : (
        <>
          <nav aria-label="Miesiące płac" className="flex flex-wrap items-center gap-3 text-sm">
            <Link
              href={`/people/payroll/${ymSegment(prev.year, prev.month)}`}
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden />
              Poprzedni miesiąc
            </Link>
            {hasNext ? (
              <Link
                href={`/people/payroll/${ymSegment(next.year, next.month)}`}
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                Następny miesiąc
                <ChevronRight className="h-4 w-4" aria-hidden />
              </Link>
            ) : null}
            {payroll ? (
              <Link href="/people/payroll" className="text-primary hover:underline">
                Wszystkie miesiące
              </Link>
            ) : null}
          </nav>

          {payroll ? (
            <>
              <CloseStepper steps={steps.steps} />
              {open && (data.warnings ?? []).length > 0 ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 px-4 py-2 text-sm text-muted-foreground">
                  <span>Przed zamknięciem: {(data.warnings ?? []).map((w) => w.message).join(" ")}</span>
                  {steps.needsAcknowledge ? (
                    <Button size="sm" variant="outline" onClick={() => setAcknowledgedWarnings(warningsKey)}>
                      Potwierdzam ostrzeżenia
                    </Button>
                  ) : (
                    <span className="font-medium text-foreground">Potwierdzone</span>
                  )}
                </div>
              ) : null}
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
                <PayoutCard people={data.people} />
                <DecisionPanel
                  rows={data.bonuses.filter((row) => row.status === "proposed")}
                  later={data.later}
                  missingRates={data.missing_rates}
                  meId={me?.id}
                  open={open}
                  canCreate={open && people.length > 0}
                  onCreate={() => setBonusOpen(true)}
                  onImport={open ? () => setImportOpen(true) : undefined}
                  onApprove={approveRow}
                  onEdit={setEditing}
                  onCancel={setDeleting}
                  approving={approve.isPending}
                />
              </div>
            </>
          ) : (
            <div className="flex flex-wrap items-end justify-between gap-3">
              <InlineStats id="payroll-month-stats" stats={monthStats(data)} />
              {open && people.length > 0 ? (
                <Button size="sm" variant="secondary" onClick={() => setBonusOpen(true)}>
                  <Plus className="h-4 w-4" aria-hidden />
                  Nowa premia
                </Button>
              ) : null}
            </div>
          )}

          {data.people.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
              {payroll
                ? "W tym miesiącu nikt z kartoteką nie był zatrudniony."
                : "Nikt z Twojego zespołu nie ma w tym miesiącu godzin ani premii."}
            </div>
          ) : (
            <PayrollPeopleTable
              people={data.people}
              scope={data.scope}
              renderTimesheetAction={(person) => {
                const label = open ? reminderAction(person, data.scope) : null;
                if (!label) return null;
                const busy = remind.isPending && remind.variables?.userId === person.user_id;
                return (
                  <button
                    type="button"
                    onClick={() => remindPerson(person)}
                    disabled={busy}
                    aria-label={`${label}: ${person.name}`}
                    className="text-xs font-medium text-primary underline-offset-2 hover:underline disabled:opacity-50"
                  >
                    {busy ? "Wysyłanie…" : label}
                  </button>
                );
              }}
            />
          )}

          {!payroll && decidable.length > 0 ? (
            <section className="space-y-2">
              <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
                Premie do decyzji
              </h2>
              <BonusTable
                rows={decidable}
                renderActions={(row) => {
                  if (!open || mine(row)) return null;
                  const decision = bonusDecision(row, me?.id);
                  return (
                    <div className="flex justify-end gap-1">
                      {decision.approve ? (
                        <Button size="sm" onClick={() => approveRow(row)} disabled={approve.isPending}>
                          Zatwierdź
                        </Button>
                      ) : null}
                      <Button size="sm" variant="quiet" onClick={() => cancelRow(row)}>
                        {decision.rejectLabel}
                      </Button>
                    </div>
                  );
                }}
              />
            </section>
          ) : null}

          <PlacementsStrip
            rows={data.in_progress}
            assignedCount={assigned.length}
            assignedOpen={assignedOpen}
            onToggleAssigned={() => setAssignedOpen((value) => !value)}
          />

          {assignedOpen ? (
            <section className="space-y-2" aria-label="Premie przyznane w tym miesiącu">
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
                  renderActions={(row) => {
                    const actions = assignedBonusActions(row, { open, payroll, meId: me?.id });
                    if (!actions.edit && !actions.cancel) return null;
                    return (
                      <div className="flex justify-end gap-1">
                        {actions.edit ? (
                          <Button size="sm" variant="ghost" onClick={() => setEditing(row)}>
                            Zmień
                          </Button>
                        ) : null}
                        {actions.cancel ? (
                          <Button size="sm" variant="quiet" onClick={() => cancelRow(row)}>
                            Anuluj
                          </Button>
                        ) : null}
                      </div>
                    );
                  }}
                />
              )}
            </section>
          ) : null}
        </>
      )}

      {importOpen ? (
        <SettlementImportDialog
          open={importOpen}
          onOpenChange={setImportOpen}
          year={year}
          month={month}
          label={data.label}
        />
      ) : null}
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
          fullEdit={payroll}
          onDelete={(row) => {
            setEditing(null);
            setDeleting(row);
          }}
        />
      ) : null}
      {deleting ? <BonusDeleteDialog row={deleting} onClose={() => setDeleting(null)} /> : null}
      {reopenOpen ? (
        <ReopenMonthDialog
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
