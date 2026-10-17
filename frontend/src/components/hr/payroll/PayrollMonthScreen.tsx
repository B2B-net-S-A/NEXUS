"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FileArchive, FileSpreadsheet, Lock, LockOpen, Plus } from "lucide-react";

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
} from "@/lib/api/hr-payroll";
import { timePaths } from "@/lib/api/hr-time";
import { resolveViewState } from "@/lib/view-state";
import { useAuthStore } from "@/store/auth";
import { formatMoney } from "@/lib/money";
import { formatIsoDatePl } from "@/lib/date-pl";
import { capitalize } from "@/lib/hr-employment-terms";
import { useUrlSyncedState, writeUrlParams } from "@/lib/url-selection";

import { BonusDialog } from "./BonusDialog";
import { BonusTable } from "./BonusTable";
import { PayrollPeopleTable } from "./PayrollPeopleTable";
import { ReopenMonthDialog } from "./ReopenMonthDialog";
import { monthStats, splitBonuses, ymSegment } from "./payroll-format";
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
  const [editing, setEditing] = useState<BonusRow | null>(null);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [downloading, setDownloading] = useState<"xlsx" | "zip" | null>(null);
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
  const tabs = payrollMonthTabs(config, payroll);
  const activeView = tabs.some((tab) => tab.value === view) ? view : MONTH_VIEW;
  const moduleTab = PAYROLL_MONTH_TABS.find((tab) => tab.value === activeView);
  const changeView = (value: string) => {
    setView(value);
    writeUrlParams({ view: value === MONTH_VIEW ? null : value, settlement: null });
  };
  const mine = (row: BonusRow) => me?.id === row.recipient_user_id;
  const canEdit = (row: BonusRow) =>
    open && !mine(row) && (payroll || row.proposed_by === me?.id);

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
            <PayrollPeopleTable people={data.people} scope={data.scope} />
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
        </>
      )}

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
