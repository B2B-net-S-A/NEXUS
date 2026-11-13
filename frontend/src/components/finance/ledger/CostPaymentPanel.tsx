"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useEntryAccount,
  useEntryPaid,
  useEntryPayment,
  type EntryPayment,
} from "@/lib/api/finance-payments";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { warsawToday } from "@/lib/warsaw-date";

import { formatAccount, paymentTone } from "./payment-model";

const LABEL = "text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground";
const CONTROL =
  "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children ?? "—"}</dd>
    </>
  );
}

function AccountForm({ data, locked }: { data: EntryPayment; locked: boolean }) {
  const save = useEntryAccount(data.entry_id);
  const { showToast } = useToast();
  const [value, setValue] = useState(data.accounts?.manual ?? "");
  // Domyślnie bez nadpisywania kartoteki — inny dostawca z tym NIP-em zostaje.
  const [remember, setRemember] = useState(false);
  if (locked) return null;
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(
          { account: value.trim() || null, remember },
          {
            onSuccess: () => showToast("Rachunek zapisany.", "success"),
            onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać rachunku."), "error"),
          },
        );
      }}
    >
      <input
        aria-label="Rachunek odbiorcy"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="PL00 0000 … albo IBAN"
        className={cn(CONTROL, "w-72 font-mono")}
      />
      {data.can_remember ? (
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Checkbox checked={remember} onCheckedChange={(checked) => setRemember(checked === true)} />
          zapamiętaj w kartotece
        </label>
      ) : null}
      <Button size="sm" variant="outline" type="submit" loading={save.isPending}>
        Zapisz rachunek
      </Button>
    </form>
  );
}

function PaidForm({ data }: { data: EntryPayment }) {
  const paid = useEntryPaid(data.entry_id);
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [paidOn, setPaidOn] = useState(warsawToday());
  const [reason, setReason] = useState("");
  if (!open) {
    return (
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        Opłacono…
      </Button>
    );
  }
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        paid.mutate(
          { amount: amount.trim() ? amount.replace(",", ".") : undefined, paid_on: paidOn, reason },
          {
            onSuccess: () => {
              showToast("Zapłata zapisana.", "success");
              setOpen(false);
            },
            onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zapisać zapłaty."), "error"),
          },
        );
      }}
    >
      <input
        aria-label="Kwota zapłaty"
        inputMode="decimal"
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        placeholder={data.to_pay ? `${data.to_pay} (całość)` : "kwota"}
        className={cn(CONTROL, "w-36 tabular-nums")}
      />
      <input
        type="date"
        aria-label="Data zapłaty"
        value={paidOn}
        max={warsawToday()}
        onChange={(event) => setPaidOn(event.target.value)}
        className={CONTROL}
      />
      <input
        aria-label="Powód"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        placeholder="np. karta firmowa"
        minLength={3}
        className={cn(CONTROL, "w-48")}
      />
      <Button size="sm" type="submit" loading={paid.isPending} disabled={reason.trim().length < 3}>
        Zapisz
      </Button>
      <Button size="sm" variant="ghost" type="button" onClick={() => setOpen(false)}>
        Anuluj
      </Button>
    </form>
  );
}

/** Karta faktury → „Płatność” (E3): stan, rachunek, paczka, zapłaty. */
export function CostPaymentPanel({ entryId, readOnly }: { entryId: number; readOnly: boolean }) {
  const payment = useEntryPayment(entryId);
  if (payment.isLoading) {
    return <p className="text-sm text-muted-foreground">Wczytywanie płatności…</p>;
  }
  if (payment.isError || !payment.data) {
    return <QueryStateNotice state="error" onRetry={() => payment.refetch()} />;
  }
  const data = payment.data;
  const payroll = data.path === "payroll";
  const inBatch = Boolean(data.batch);
  return (
    <section className="space-y-2.5 rounded-lg border border-border bg-card p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className={LABEL}>Płatność</h2>
        <Badge size="sm" variant={paymentTone(data.state)}>
          {data.state_label}
        </Badge>
      </div>
      {payroll ? (
        <p className="text-sm text-muted-foreground">{data.path_label}</p>
      ) : null}
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-sm">
        <Row label="Termin">{data.due_date ? formatIsoDatePl(data.due_date) : null}</Row>
        <Row label="Brutto">{formatMoney(data.gross_amount, data.currency)}</Row>
        {!payroll ? (
          <>
            <Row label="Do zapłaty">
              {data.payable_problem ? (
                <span className="text-warning-muted-foreground">{data.payable_problem}</span>
              ) : (
                <>
                  {formatMoney(data.to_pay, data.currency)}
                  {data.amount_note ? (
                    <span className="block text-xs text-muted-foreground">{data.amount_note}</span>
                  ) : null}
                </>
              )}
            </Row>
            <Row label="Tryb">
              {data.mode_label
                ? `${data.mode_label}${data.mode_suggested ? " (z kwoty — do potwierdzenia przy paczce)" : ""}`
                : data.mode_problem}
            </Row>
            <Row label="Rachunek">
              {data.account ? (
                <span>
                  <span className="font-mono text-xs">{formatAccount(data.account)}</span>
                  {data.account_source_label ? (
                    <span className="text-muted-foreground"> · {data.account_source_label}</span>
                  ) : null}
                  {data.account_note ? (
                    <span className="block text-xs text-warning-muted-foreground">
                      {data.account_note}
                    </span>
                  ) : null}
                </span>
              ) : (
                <span className="text-warning-muted-foreground">brak — wpisz poniżej</span>
              )}
            </Row>
          </>
        ) : null}
        <Row label="Zapłacona">
          {data.paid_on
            ? `${formatIsoDatePl(data.paid_on)}${data.paid_source_label ? ` · ${data.paid_source_label}` : ""}`
            : null}
        </Row>
        {data.batch ? (
          <Row label="Paczka">
            #{data.batch.id} · {formatIsoDatePl(data.batch.execution_date)} ·{" "}
            {formatMoney(data.batch.amount, data.currency)}
          </Row>
        ) : null}
      </dl>
      {!payroll && !readOnly ? (
        <div className="space-y-2">
          <AccountForm key={data.accounts?.manual ?? ""} data={data} locked={inBatch} />
          {inBatch ? (
            <p className="text-xs text-muted-foreground">
              Faktura jest w paczce czekającej na bank — „Opłacono” i zmiana rachunku po
              zdjęciu z paczki (Przelewy → Paczki → Pozycje).
            </p>
          ) : data.state !== "paid" && !data.payable_problem ? (
            <PaidForm data={data} />
          ) : null}
        </div>
      ) : null}
      {data.records && data.records.length > 0 ? (
        <ol className="space-y-1 text-sm">
          {data.records.map((record) => (
            <li key={record.id}>
              <span className="text-muted-foreground">{formatIsoDatePl(record.booked_on)}</span> ·{" "}
              {formatMoney(record.amount, record.currency)} ·{" "}
              {record.kind === "manual" ? "ręcznie" : "wyciąg"}
              {record.reason ? <span className="text-muted-foreground"> · {record.reason}</span> : null}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

export default CostPaymentPanel;
