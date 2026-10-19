"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { SETTLEMENT_TONE, accountLabel, amountWithBasis, queueStatus } from "@/components/hr/me/settlement-format";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile } from "@/lib/api/hr";
import {
  settlementPaths,
  useApproveSettlement,
  useConfirmOverride,
  useMarkPaid,
  useRequestCorrection,
  useRequestOverride,
  useSettlementDetail,
  useWithdrawOverride,
  type SettlementDetail,
} from "@/lib/api/hr-settlements";
import { CALM_AMOUNT } from "@/lib/calm-table";
import { formatDayMonthPl, formatIsoDatePl } from "@/lib/date-pl";
import { capitalize } from "@/lib/hr-employment-terms";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { warsawToday } from "@/lib/warsaw-date";

type Panel = "none" | "override" | "paid";

function Column({
  title,
  rows,
  total,
  footer,
}: {
  title: string;
  rows: { key: string; label: string; amount: string | null }[];
  total: string;
  footer?: string | null;
}) {
  return (
    <section className="min-w-0 space-y-1 rounded-md border border-border p-3">
      <h3 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        {title}
      </h3>
      <table className="w-full text-sm">
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-b border-border/60">
              <td className="py-1 pr-2 text-foreground">{row.label}</td>
              <td className={cn(CALM_AMOUNT, "py-1 text-foreground")}>{row.amount}</td>
            </tr>
          ))}
          <tr>
            <td className="pt-1.5 font-semibold text-foreground">Netto</td>
            <td className={cn(CALM_AMOUNT, "pt-1.5 font-semibold text-foreground")}>{total}</td>
          </tr>
        </tbody>
      </table>
      {footer ? <p className="break-all text-xs text-muted-foreground">{footer}</p> : null}
    </section>
  );
}

/** Pozycje z NEXUSA obok pozycji faktury z KSeF (M4). */
export function Comparison({ detail }: { detail: SettlementDetail }) {
  const nexus = detail.expected_items.map((item, index) => ({
    key: `n-${index}`,
    label: item.label,
    amount: formatMoney(item.amount, detail.currency),
  }));
  const invoiceRows = detail.invoices.flatMap((invoice) =>
    invoice.items.length > 0
      ? invoice.items.map((item, index) => ({
          key: `i-${invoice.id}-${index}`,
          label: [item.name ?? "Pozycja", item.quantity ? `${item.quantity} ${item.unit ?? ""}`.trim() : null]
            .filter(Boolean)
            .join(" · "),
          amount: formatMoney(item.net ?? null, detail.currency),
        }))
      : [
          {
            key: `i-${invoice.id}`,
            label: `${invoice.kind === "correction" ? "Korekta" : "Faktura"} ${invoice.invoice_number}`,
            amount: formatMoney(invoice.net_amount, detail.currency),
          },
        ],
  );
  const first = detail.invoices[0];
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <Column
        title="Z NEXUSA (zamknięty miesiąc)"
        rows={nexus}
        total={formatMoney(detail.expected_amount, detail.currency)}
      />
      {first ? (
        <Column
          title={`Faktura ${first.invoice_number}${first.source === "ksef" ? " z KSeF" : " (PDF)"}`}
          rows={invoiceRows}
          total={formatMoney(detail.invoice_net, detail.currency)}
          footer={first.ksef_number ? `KSeF ${first.ksef_number}` : null}
        />
      ) : (
        <section className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
          Faktura jeszcze nie przyszła z KSeF.
        </section>
      )}
    </div>
  );
}

interface SettlementDetailDialogProps {
  settlementId: number;
  onClose: () => void;
}

/**
 * Rozliczenie osoby — porównanie i decyzje Płac (M4, R7, R10): „Poproś
 * o korektę”, „Uznaj różnicę” (powód + druga osoba), „Zatwierdź do zapłaty”
 * i awaryjne „Oznacz jako opłacone”. Własnego rozliczenia nikt nie rusza.
 */
export function SettlementDetailDialog({ settlementId, onClose }: SettlementDetailDialogProps) {
  const query = useSettlementDetail(settlementId);
  const approve = useApproveSettlement();
  const correction = useRequestCorrection();
  const override = useRequestOverride();
  const confirm = useConfirmOverride();
  const withdraw = useWithdrawOverride();
  const markPaid = useMarkPaid();
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [panel, setPanel] = useState<Panel>("none");
  // Osobne powody dla dwóch decyzji: tekst uznania różnicy nie może trafić
  // do ręcznego „opłacono” (i odwrotnie) — audyt A2, 19.10.2026.
  const [overrideReason, setOverrideReason] = useState("");
  const [paidReason, setPaidReason] = useState("");
  const [paidOn, setPaidOn] = useState(warsawToday());
  const [paidAmount, setPaidAmount] = useState("");
  const [error, setError] = useState<string | null>(null);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  const detail = query.data;
  const title = detail ? `${detail.name} · ${capitalize(detail.label)}` : "Rozliczenie";

  const run = (promise: Promise<unknown>, done: string) => {
    setError(null);
    promise
      .then(() => {
        showToast(done, "success");
        setPanel("none");
        setOverrideReason("");
        setPaidReason("");
      })
      .catch((err) => setError(apiErrorMessage(err, "Nie udało się zapisać decyzji.")));
  };

  const askCorrection = async () => {
    if (!detail) return;
    const ok = await askConfirm({
      title: "Poprosić o korektę faktury?",
      description: `${detail.name} dostanie wiadomość z porównaniem (bez kwot w treści). Faktura korygująca z KSeF podepnie się sama.`,
      confirmLabel: "Poproś o korektę",
      cancelLabel: "Wróć",
    });
    if (ok) run(correction.mutateAsync(detail.id), "Prośba o korektę wysłana");
  };

  const submitOverride = () => {
    if (!detail) return;
    if (overrideReason.trim().length < 3) {
      setError("Podaj powód uznania różnicy.");
      return;
    }
    run(
      override.mutateAsync({ id: detail.id, reason: overrideReason.trim() }),
      "Uznanie czeka na drugą osobę",
    );
  };

  const submitPaid = () => {
    if (!detail) return;
    if (!paidAmount.trim() || Number(paidAmount.replace(",", ".")) <= 0) {
      setError("Podaj kwotę przelewu.");
      return;
    }
    if (paidReason.trim().length < 3) {
      setError("Podaj powód ręcznego „opłacono”.");
      return;
    }
    run(
      markPaid.mutateAsync({
        id: detail.id,
        amount: paidAmount.replace(/\s/g, "").replace(",", "."),
        paid_on: paidOn,
        reason: paidReason.trim(),
      }),
      "Oznaczono jako opłacone",
    );
  };

  const download = async () => {
    if (!detail) return;
    try {
      await downloadHrFile(settlementPaths.pdf(detail.id), `rozliczenie-zlecenia-${detail.id}.pdf`);
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać PDF-u."), "error");
    }
  };

  const busy =
    approve.isPending ||
    correction.isPending ||
    override.isPending ||
    confirm.isPending ||
    withdraw.isPending ||
    markPaid.isPending;

  return (
    <AppModal
      open
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
      size="xl"
      title={title}
      description={
        detail
          ? `${detail.form_short} · ${amountWithBasis(detail.expected_amount, detail.currency, detail.amount_basis)} z zamkniętego miesiąca`
          : undefined
      }
      footer={
        detail ? (
          <div className="flex w-full flex-wrap items-center justify-end gap-2">
            {detail.has_pdf ? (
              <Button variant="ghost" onClick={download}>
                Pobierz PDF
              </Button>
            ) : null}
            {detail.can_request_correction ? (
              <Button variant="outline" onClick={askCorrection} disabled={busy}>
                Poproś o korektę
              </Button>
            ) : null}
            {detail.can_request_override ? (
              <Button variant="outline" onClick={() => setPanel("override")} disabled={busy}>
                Uznaj różnicę
              </Button>
            ) : null}
            {detail.override?.can_confirm ? (
              <Button
                onClick={() => run(confirm.mutateAsync(detail.id), "Różnica uznana")}
                disabled={busy}
              >
                Potwierdź uznanie
              </Button>
            ) : null}
            {detail.can_mark_paid ? (
              <Button variant="ghost" onClick={() => setPanel("paid")} disabled={busy}>
                Oznacz jako opłacone
              </Button>
            ) : null}
            {detail.can_approve ? (
              <Button
                onClick={() => run(approve.mutateAsync(detail.id), "Zatwierdzone do zapłaty")}
                disabled={busy}
              >
                Zatwierdź do zapłaty
              </Button>
            ) : null}
          </div>
        ) : undefined
      }
    >
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie porównania…</p>
      ) : state !== "ready" || !detail ? (
        <QueryStateNotice
          state={state === "forbidden" || state === "not_found" ? state : "error"}
          description={state === "not_found" ? "Nie ma takiego rozliczenia." : undefined}
          onRetry={() => query.refetch()}
        />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <StatusDot tone={SETTLEMENT_TONE[detail.status]}>{queueStatus(detail)}</StatusDot>
            <span className="text-muted-foreground">
              Termin: {detail.due_on ? formatIsoDatePl(detail.due_on) : "—"}
            </span>
            <span className="text-muted-foreground">
              Rachunek: {accountLabel(detail.account_last4, detail.account_source)}
            </span>
            {detail.timesheet_approved_on ? (
              <span className="text-muted-foreground">
                Raport potwierdzony {formatDayMonthPl(detail.timesheet_approved_on)}
              </span>
            ) : null}
          </div>
          {detail.employment_type === "b2b" ? (
            <Comparison detail={detail} />
          ) : (
            <section className="space-y-1 rounded-md border border-border p-3">
              {detail.expected_items.map((item, index) => (
                <p key={index} className="flex justify-between gap-3 text-sm text-foreground">
                  <span>{item.label}</span>
                  <span className="tabular-nums">{formatMoney(item.amount, detail.currency)}</span>
                </p>
              ))}
            </section>
          )}
          {detail.explain.length > 0 ? (
            <section className="rounded-md bg-muted/40 p-3 text-sm">
              <h3 className="mb-1 font-semibold text-foreground">Co się nie zgadza</h3>
              <ul className="list-disc space-y-0.5 pl-5 text-foreground">
                {detail.explain.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted-foreground">
                „Poproś o korektę” wysyła osobie wiadomość; korekta z KSeF podepnie się sama.
                „Uznaj różnicę” wymaga powodu i drugiej osoby z Płac.
              </p>
            </section>
          ) : null}
          {detail.override ? (
            <section className="rounded-md border border-border p-3 text-sm">
              <p className="text-foreground">
                Uznanie różnicy: {detail.override.reason}
                <span className="text-muted-foreground">
                  {" "}
                  · {detail.override.requested_by_name ?? "Płace"}
                  {detail.override.confirmed_by_name
                    ? ` · potwierdził(a) ${detail.override.confirmed_by_name}`
                    : " · czeka na drugą osobę"}
                </span>
              </p>
              {!detail.override.confirmed_by_name && !detail.mine ? (
                <Button
                  size="sm"
                  variant="quiet"
                  className="mt-1"
                  onClick={() => run(withdraw.mutateAsync(detail.id), "Uznanie cofnięte")}
                  disabled={busy}
                >
                  Cofnij uznanie
                </Button>
              ) : null}
            </section>
          ) : null}
          {detail.mine ? (
            <p className="text-sm text-muted-foreground">
              To Twoje rozliczenie — decyzje podejmuje inna osoba z Płac.
            </p>
          ) : null}
          {panel === "override" ? (
            <FormField label="Powód uznania różnicy" htmlFor="settlement-override-reason">
              <Input
                id="settlement-override-reason"
                value={overrideReason}
                maxLength={500}
                onChange={(event) => setOverrideReason(event.target.value)}
              />
              <div className="mt-2 flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={() => setPanel("none")}>
                  Wróć
                </Button>
                <Button size="sm" onClick={submitOverride} disabled={busy}>
                  Poproś drugą osobę
                </Button>
              </div>
            </FormField>
          ) : null}
          {panel === "paid" ? (
            <div className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-3">
              <FormField label="Kwota przelewu" htmlFor="settlement-paid-amount">
                <Input
                  id="settlement-paid-amount"
                  inputMode="decimal"
                  value={paidAmount}
                  onChange={(event) => setPaidAmount(event.target.value)}
                />
              </FormField>
              <FormField label="Dzień zapłaty" htmlFor="settlement-paid-on">
                <Input
                  id="settlement-paid-on"
                  type="date"
                  value={paidOn}
                  max={warsawToday()}
                  onChange={(event) => setPaidOn(event.target.value)}
                />
              </FormField>
              <FormField label="Powód" htmlFor="settlement-paid-reason">
                <Input
                  id="settlement-paid-reason"
                  value={paidReason}
                  maxLength={500}
                  onChange={(event) => setPaidReason(event.target.value)}
                />
              </FormField>
              <div className="flex justify-end gap-2 sm:col-span-3">
                <Button variant="ghost" size="sm" onClick={() => setPanel("none")}>
                  Wróć
                </Button>
                <Button size="sm" onClick={submitPaid} disabled={busy}>
                  Oznacz jako opłacone
                </Button>
              </div>
            </div>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
      )}
      {confirmDialog}
    </AppModal>
  );
}
