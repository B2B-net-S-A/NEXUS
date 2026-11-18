"use client";

import * as React from "react";
import { Download, FileText, Pencil, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage } from "@/lib/api-error";
import {
  boardArchivedReportPath,
  boardReportPath,
  reportFileName,
  useArchiveBoardReport,
  useBoardCash,
  useBoardOutlook,
  useBoardReports,
  useDeleteBoardCash,
  useDeleteBoardReport,
  useSaveBoardCash,
  type BoardOutlook,
  type InvestorView,
  type ReportKind,
  type ReportPeriod,
} from "@/lib/api/supervisory-board";
import { downloadAuthenticatedFile } from "@/lib/authenticated-files";
import { cn, formatDate } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";

const MONTHS = [
  "styczeń",
  "luty",
  "marzec",
  "kwiecień",
  "maj",
  "czerwiec",
  "lipiec",
  "sierpień",
  "wrzesień",
  "październik",
  "listopad",
  "grudzień",
];

export function mlnShort(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toLocaleString("pl-PL", { minimumFractionDigits: digits, maximumFractionDigits: digits })} mln`;
}

function range(low: number | null | undefined, high: number | null | undefined): string {
  if (low == null || high == null) return "—";
  if (Math.abs(high - low) < 0.05) return mlnShort(low);
  return `${low.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}–${mlnShort(high)}`;
}

/** Podpis bazy wyceny i zdolności (czysta funkcja — test w __tests__). */
export function basisNote(outlook: BoardOutlook): string {
  const c = outlook.current;
  if (c.base_year === null) {
    return "Czeka na sprawozdanie: wgraj e-Sprawozdanie albo wpisz rok w zakładce Analiza.";
  }
  const shift =
    outlook.profit_shift_applied && outlook.profit_window && c.ebitda_shift != null
      ? ` ${c.ebitda_shift >= 0 ? "+" : "−"} ${mlnShort(Math.abs(c.ebitda_shift))} zmiany zysku brutto z faktur (${outlook.profit_window.from}–${outlook.profit_window.to} wobec ${c.base_year})`
      : "";
  return `EBITDA ${mlnShort(c.ebitda)} = ${c.base_year} ze sprawozdania ${mlnShort(c.ebitda_base)}${shift}. Dług netto ${mlnShort(c.net_debt)}.`;
}

function investorSub(view: InvestorView | undefined): string {
  if (!view || view.ev === null) return "brak EBITDA";
  return `${view.multiple.toLocaleString("pl-PL")}× EBITDA · przedział ${view.range[0]}–${view.range[1]}×: ${range(view.equity_low, view.equity_high)}`;
}

export function FinancePanel() {
  const outlook = useBoardOutlook();
  const isAdmin = hasRole(useAuthStore((s) => s.user), "admin");
  const [cashOpen, setCashOpen] = React.useState(false);
  const [reportsOpen, setReportsOpen] = React.useState(false);
  const data = outlook.data;
  return (
    <section className="min-w-0 rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-foreground">Finanse spółki</h2>
        <span className="text-[11px] text-muted-foreground">mln zł</span>
      </div>
      {outlook.isError ? (
        <p className="text-[12px] text-destructive">Nie udało się wczytać finansów. Odśwież stronę.</p>
      ) : !data ? (
        <div className="h-48 animate-pulse rounded-md bg-muted" aria-hidden />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Mini
              label="Stan gotówki"
              value={mlnShort(data.cash?.amount ?? data.statement_cash?.amount)}
              sub={
                data.cash
                  ? `na ${formatDate(data.cash.as_of)} · wpis Zarządu`
                  : data.statement_cash
                    ? `31.12.${data.statement_cash.year} wg sprawozdania`
                    : "Zarząd wpisuje stan z wyciągów"
              }
              action={
                isAdmin ? (
                  <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => setCashOpen(true)}>
                    <Pencil className="mr-1 h-3.5 w-3.5" /> Wpisz
                  </Button>
                ) : null
              }
            />
            <Mini
              label="Zdolność kredytowa"
              value={mlnShort(data.current.credit?.headroom)}
              sub={
                data.current.credit?.max_net_debt != null
                  ? `nowy dług do ${data.current.credit.debt_to_ebitda}× EBITDA (${mlnShort(data.current.credit.max_net_debt)})`
                  : "brak EBITDA ze sprawozdania"
              }
            />
            <Mini
              label="Wartość spółki — inwestor finansowy"
              value={mlnShort(data.current.valuation?.financial.equity)}
              sub={investorSub(data.current.valuation?.financial)}
            />
            <Mini
              label="Wartość spółki — inwestor branżowy"
              value={mlnShort(data.current.valuation?.strategic.equity)}
              sub={investorSub(data.current.valuation?.strategic)}
            />
            <Mini
              label={`Symulacja ${data.year_end.year}: sprzedaż`}
              value={range(data.year_end.sales_low, data.year_end.sales_high)}
              sub={
                data.year_end.reason ??
                `wykonanie ${data.year_end.actual_months} mies. ${mlnShort(data.year_end.actual_sales)} + prognoza z kontraktów${
                  data.year_end.plan_sales != null ? ` · budżet ${mlnShort(data.year_end.plan_sales)}` : ""
                }`
              }
            />
            <Mini
              label={`Symulacja ${data.year_end.year}: zysk brutto`}
              value={range(data.year_end.profit_low, data.year_end.profit_high)}
              sub={
                data.year_end.profit_pct != null
                  ? `${data.year_end.profit_pct.toLocaleString("pl-PL")}% sprzedaży (12 mies. kroczących)`
                  : "brak udziału kosztów"
              }
            />
          </div>
          <p className="mt-2 text-[11px] leading-snug text-muted-foreground">{basisNote(data)}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
            <Button size="sm" onClick={() => setReportsOpen(true)}>
              <FileText className="mr-1.5 h-4 w-4" /> Raporty do pobrania
            </Button>
            <span className="text-[11px] text-muted-foreground">miesięczny, roczny, budżet i archiwum</span>
          </div>
        </>
      )}
      {cashOpen ? <CashDialog onClose={() => setCashOpen(false)} /> : null}
      {reportsOpen ? <ReportsDialog isAdmin={isAdmin} onClose={() => setReportsOpen(false)} /> : null}
    </section>
  );
}

function Mini({
  label,
  value,
  sub,
  action,
}: {
  label: string;
  value: string;
  sub?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-md border border-border px-3 py-2.5">
      <div className="flex items-start justify-between gap-1">
        <div className="text-[12px] font-medium leading-tight text-muted-foreground">{label}</div>
        {action}
      </div>
      <div className="mt-1 text-[19px] font-semibold leading-tight tabular-nums tracking-tight text-foreground">{value}</div>
      {sub ? <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{sub}</div> : null}
    </div>
  );
}

// ── Stan gotówki (admin) ─────────────────────────────────────────────────────

function CashDialog({ onClose }: { onClose: () => void }) {
  const { showToast } = useToast();
  const cash = useBoardCash();
  const save = useSaveBoardCash();
  const remove = useDeleteBoardCash();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const today = new Date().toISOString().slice(0, 10);
  const [asOf, setAsOf] = React.useState(today);
  const [amount, setAmount] = React.useState("");
  const [note, setNote] = React.useState("");
  const parsed = Number(amount.replace(/\s/g, "").replace(",", "."));
  const valid = amount.trim() !== "" && Number.isFinite(parsed) && asOf <= today;

  const onSave = () =>
    save.mutate(
      { as_of: asOf, amount: String(Math.round(parsed * 100) / 100), note: note.trim() || null },
      {
        onSuccess: () => {
          showToast("Zapisano stan gotówki.");
          setAmount("");
          setNote("");
        },
        onError: (e) => showToast(apiErrorMessage(e, "Nie udało się zapisać stanu gotówki."), "error"),
      },
    );

  const onDelete = async (id: number, day: string) => {
    const ok = await askConfirm({
      title: "Usunąć wpis?",
      description: `Stan gotówki na ${formatDate(day)} zniknie z pulpitu i raportów.`,
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(id, {
      onError: (e) => showToast(apiErrorMessage(e, "Nie udało się usunąć wpisu."), "error"),
    });
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title="Stan gotówki"
      description="Suma środków na rachunkach na koniec dnia, w złotych (z wyciągów). Pulpit pokazuje najnowszy wpis."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Zamknij
          </Button>
          <Button onClick={onSave} disabled={!valid || save.isPending}>
            Zapisz
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="board-cash-date">Na dzień</Label>
          <Input id="board-cash-date" type="date" value={asOf} max={today} onChange={(e) => setAsOf(e.target.value)} />
        </div>
        <div className="space-y-1">
          <Label htmlFor="board-cash-amount">Kwota (zł)</Label>
          <Input
            id="board-cash-amount"
            inputMode="decimal"
            placeholder="np. 8 250 000"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <Label htmlFor="board-cash-note">Uwaga (opcjonalnie)</Label>
          <Input id="board-cash-note" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
      </div>
      {cash.data?.items.length ? (
        <ul className="mt-4 divide-y divide-border rounded-md border border-border text-[13px]">
          {cash.data.items.map((item) => (
            <li key={item.id} className="flex items-center justify-between gap-2 px-3 py-1.5">
              <span>{formatDate(item.as_of)}</span>
              <span className="tabular-nums">{item.amount.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} zł</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{item.note ?? ""}</span>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2"
                aria-label={`Usuń wpis z ${formatDate(item.as_of)}`}
                onClick={() => void onDelete(item.id, item.as_of)}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {confirmDialog}
    </AppModal>
  );
}

// ── Raporty do pobrania ──────────────────────────────────────────────────────

const KIND_OPTIONS: { value: ReportKind; label: string }[] = [
  { value: "monthly", label: "Miesięczny" },
  { value: "annual", label: "Roczny" },
  { value: "budget", label: "Budżet" },
];

function ReportsDialog({ isAdmin, onClose }: { isAdmin: boolean; onClose: () => void }) {
  const { showToast } = useToast();
  const reports = useBoardReports();
  const archive = useArchiveBoardReport();
  const remove = useDeleteBoardReport();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const now = new Date();
  const lastClosed = now.getMonth() === 0 ? { y: now.getFullYear() - 1, m: 12 } : { y: now.getFullYear(), m: now.getMonth() };
  const [period, setPeriod] = React.useState<ReportPeriod>({ kind: "monthly", year: lastClosed.y, month: lastClosed.m });
  const [busy, setBusy] = React.useState(false);
  const years = reports.data?.years ?? [now.getFullYear()];
  const yearOptions = period.kind === "budget" && !years.includes(now.getFullYear() + 1) ? [now.getFullYear() + 1, ...years] : years;
  const maxMonth = period.year === now.getFullYear() ? now.getMonth() + 1 : 12;

  const download = async () => {
    setBusy(true);
    try {
      await downloadAuthenticatedFile(boardReportPath(period), reportFileName(period));
    } catch (e) {
      showToast(apiErrorMessage(e, "Nie udało się przygotować raportu."), "error");
    } finally {
      setBusy(false);
    }
  };

  const onArchive = () =>
    archive.mutate(period, {
      onSuccess: () => showToast("Raport zapisany w archiwum."),
      onError: (e) => showToast(apiErrorMessage(e, "Nie udało się zapisać raportu."), "error"),
    });

  const onDelete = async (id: number, title: string) => {
    const ok = await askConfirm({
      title: "Usunąć raport z archiwum?",
      description: `„${title}” zniknie z archiwum Rady. Raport z bieżących danych da się pobrać dalej.`,
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(id, {
      onError: (e) => showToast(apiErrorMessage(e, "Nie udało się usunąć raportu."), "error"),
    });
  };

  return (
    <AppModal
      open
      size="lg"
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      title="Raporty dla Rady"
      description="Raport liczy się z danych na dziś (PDF). Zapisany w archiwum nie zmienia się, gdy spłyną spóźnione faktury."
      footer={
        <Button variant="outline" onClick={onClose}>
          Zamknij
        </Button>
      }
    >
      <div className="space-y-3">
        <SegmentedRadio<ReportKind>
          label="Rodzaj raportu"
          size="sm"
          value={period.kind}
          onChange={(kind) => setPeriod((p) => ({ ...p, kind }))}
          options={KIND_OPTIONS}
        />
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-28 space-y-1">
            <Label htmlFor="board-report-year">Rok</Label>
            <Select value={String(period.year)} onValueChange={(v) => setPeriod((p) => ({ ...p, year: Number(v) }))}>
              <SelectTrigger id="board-report-year">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {yearOptions.map((y) => (
                  <SelectItem key={y} value={String(y)}>
                    {y}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {period.kind === "monthly" ? (
            <div className="w-40 space-y-1">
              <Label htmlFor="board-report-month">Miesiąc</Label>
              <Select
                value={String(Math.min(period.month ?? 1, maxMonth))}
                onValueChange={(v) => setPeriod((p) => ({ ...p, month: Number(v) }))}
              >
                <SelectTrigger id="board-report-month">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MONTHS.slice(0, maxMonth).map((label, i) => (
                    <SelectItem key={label} value={String(i + 1)}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}
          <Button onClick={() => void download()} disabled={busy}>
            <Download className="mr-1.5 h-4 w-4" /> {busy ? "Przygotowuję…" : "Pobierz PDF"}
          </Button>
          {isAdmin ? (
            <Button variant="outline" onClick={onArchive} disabled={archive.isPending}>
              Zapisz w archiwum
            </Button>
          ) : null}
        </div>
        <div>
          <h3 className="mb-1.5 text-[13px] font-semibold text-foreground">Archiwum</h3>
          {reports.isError ? (
            <p className="text-[12px] text-destructive">Nie udało się wczytać archiwum.</p>
          ) : reports.isSuccess && reports.data.items.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">
              Archiwum jest puste. {isAdmin ? "Zapisz raport, żeby Rada miała wersję omawianą na posiedzeniu." : ""}
            </p>
          ) : (
            <ul className="divide-y divide-border rounded-md border border-border text-[13px]">
              {(reports.data?.items ?? []).map((item) => (
                <li key={item.id} className="flex items-center gap-2 px-3 py-1.5">
                  <span className="min-w-0 flex-1 truncate">{item.title}</span>
                  <span className={cn("shrink-0 text-[11px] text-muted-foreground")}>
                    zapisany {item.created_at ? formatDate(item.created_at) : "—"}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-7 px-2"
                    aria-label={`Pobierz ${item.title}`}
                    onClick={() =>
                      void downloadAuthenticatedFile(boardArchivedReportPath(item.id), item.file_name).catch((e) =>
                        showToast(apiErrorMessage(e, "Nie udało się pobrać raportu."), "error"),
                      )
                    }
                  >
                    <Download className="h-3.5 w-3.5" />
                  </Button>
                  {isAdmin ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-7 px-2"
                      aria-label={`Usuń ${item.title}`}
                      onClick={() => void onDelete(item.id, item.title)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      {confirmDialog}
    </AppModal>
  );
}
