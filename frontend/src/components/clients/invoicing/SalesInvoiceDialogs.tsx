"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useAssignCredit,
  useAssignSalesInvoice,
  useAssignmentOptions,
  useIgnoreCredit,
  useInvoiceReason,
  useMarkSalesPaid,
  type AssignmentOption,
  type InvoiceDecision,
  type SalesCredit,
  type SalesInvoice,
} from "@/lib/api/client-invoicing";
import { formatMoney } from "@/lib/money";
import { warsawToday } from "@/lib/warsaw-date";

import { splitPeriod } from "./invoicing-format";

function ErrorLine({ error }: { error: string | null }) {
  return error ? (
    <p role="alert" className="mt-3 text-sm text-destructive">
      {error}
    </p>
  ) : null;
}

const optionKey = (option: AssignmentOption) =>
  option.group_id ? `g${option.group_id}` : `o${option.order_id}`;

/** „Przypisz” — zamówienie (albo kilka, albo jedna osoba z zamówienia MD) w miesiącu faktury. */
export function AssignInvoiceDialog({
  invoice,
  fallbackPeriod,
  onClose,
}: {
  invoice: SalesInvoice;
  fallbackPeriod: string;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const period = invoice.period ?? fallbackPeriod;
  const options = useAssignmentOptions(invoice.id, invoice.client_id, period);
  const assign = useAssignSalesInvoice();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const list = options.data?.options ?? [];

  const toggle = (key: string, on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });

  const submit = () => {
    const targets = list
      .filter((option) => picked.has(optionKey(option)))
      .map((option) =>
        option.group_id ? { group_id: option.group_id } : { order_id: option.order_id ?? undefined },
      );
    if (!targets.length) {
      setError("Zaznacz zamówienie, którego dotyczy faktura.");
      return;
    }
    assign.mutate(
      { invoiceId: invoice.id, targets, ...splitPeriod(period) },
      {
        onSuccess: () => {
          showToast("Faktura przypisana", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się przypisać faktury.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`Przypisz fakturę ${invoice.invoice_number}`}
      description={`Netto ${formatMoney(invoice.net, invoice.currency)}. Zamówienia klienta za ${period}.`}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={assign.isPending || !list.length}>
            {assign.isPending ? "Zapisywanie…" : "Przypisz"}
          </Button>
        </>
      }
    >
      {options.isLoading ? (
        <p className="text-sm text-muted-foreground">Wczytywanie zamówień…</p>
      ) : options.isError ? (
        <p className="text-sm text-destructive">
          {apiErrorMessage(options.error, "Nie udało się wczytać zamówień.")}
        </p>
      ) : !invoice.client_id ? (
        <p className="text-sm text-muted-foreground">
          NIP nabywcy nie należy do żadnego klienta w NEXUSIE. Dopisz NIP w profilu klienta —
          kolejne pobranie dopasuje fakturę samo — albo pomiń fakturę.
        </p>
      ) : list.length === 0 ? (
        <p className="text-sm text-muted-foreground">Klient nie ma zamówień w tym miesiącu.</p>
      ) : (
        <ul className="max-h-[50dvh] space-y-1.5 overflow-y-auto">
          {list.map((option) => {
            const key = optionKey(option);
            return (
              <li key={key} className="flex items-start gap-2 text-sm">
                <Checkbox
                  id={`assign-${key}`}
                  checked={picked.has(key)}
                  onCheckedChange={(value) => toggle(key, value === true)}
                />
                <label htmlFor={`assign-${key}`} className="min-w-0 flex-1 cursor-pointer">
                  <span className="block truncate">{option.label}</span>
                  <span className="block text-xs text-muted-foreground">
                    do faktury {formatMoney(option.expected_net, option.currency)}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <ErrorLine error={error} />
    </AppModal>
  );
}

const REASON_COPY: Record<InvoiceDecision, { title: string; action: string; hint: string }> = {
  ignore: {
    title: "Pomiń fakturę",
    action: "Pomiń",
    hint: "Np. sprzedaż sprzętu albo refaktura spoza zamówień.",
  },
  "accept-difference": {
    title: "Uznaj różnicę",
    action: "Uznaj różnicę",
    hint: "Np. klient potwierdził 19,5 MD zamiast raportu z arkusza.",
  },
};

export function InvoiceReasonDialog({
  invoice,
  action,
  onClose,
}: {
  invoice: SalesInvoice;
  action: InvoiceDecision;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const decide = useInvoiceReason();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const copy = REASON_COPY[action];

  const submit = () => {
    if (reason.trim().length < 3) {
      setError("Napisz powód (co najmniej 3 znaki).");
      return;
    }
    decide.mutate(
      { invoiceId: invoice.id, action, reason: reason.trim() },
      {
        onSuccess: () => {
          showToast(action === "ignore" ? "Faktura pominięta" : "Różnica uznana", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać decyzji.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`${copy.title} · ${invoice.invoice_number}`}
      description={
        action === "accept-difference" && invoice.difference
          ? `Różnica ${formatMoney(invoice.difference, invoice.currency)}. Uznanie dotyczy tej kwoty — inna różnica wróci do sprawdzenia.`
          : "Faktura zniknie z listy do przypisania. Decyzję można cofnąć."
      }
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={decide.isPending}>
            {decide.isPending ? "Zapisywanie…" : copy.action}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor="sales-invoice-reason">
        <Textarea
          id="sales-invoice-reason"
          value={reason}
          maxLength={500}
          rows={3}
          onChange={(event) => setReason(event.target.value)}
          placeholder={copy.hint}
        />
      </FormField>
      <ErrorLine error={error} />
    </AppModal>
  );
}

export function MarkPaidDialog({
  invoice,
  onClose,
}: {
  invoice: SalesInvoice;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const mark = useMarkSalesPaid();
  const [amount, setAmount] = useState(invoice.to_pay);
  const [paidOn, setPaidOn] = useState(warsawToday());
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const value = amount.replace(/\s/g, "").replace(",", ".");
    if (!/^\d+(\.\d{1,2})?$/.test(value) || Number(value) <= 0) {
      setError("Wpisz kwotę większą od zera, z groszami po przecinku.");
      return;
    }
    if (reason.trim().length < 3) {
      setError("Napisz, skąd wiadomo o zapłacie (co najmniej 3 znaki).");
      return;
    }
    mark.mutate(
      { invoiceId: invoice.id, amount: value, paid_on: paidOn, reason: reason.trim() },
      {
        onSuccess: () => {
          showToast("Zapisano zapłatę", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać zapłaty.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`Opłacono · ${invoice.invoice_number}`}
      description={`Do zapłaty ${formatMoney(invoice.to_pay, invoice.currency)}. Zapłata spoza wyciągu, np. kompensata.`}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={mark.isPending}>
            {mark.isPending ? "Zapisywanie…" : "Zapisz zapłatę"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label={`Kwota (${invoice.currency})`} htmlFor="sales-paid-amount">
          <Input
            id="sales-paid-amount"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
        </FormField>
        <FormField label="Data zapłaty" htmlFor="sales-paid-on">
          <Input
            id="sales-paid-on"
            type="date"
            max={warsawToday()}
            value={paidOn}
            onChange={(event) => setPaidOn(event.target.value)}
          />
        </FormField>
      </div>
      <FormField label="Powód" htmlFor="sales-paid-reason" className="mt-3">
        <Textarea
          id="sales-paid-reason"
          value={reason}
          maxLength={500}
          rows={2}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Np. kompensata z notą księgową."
        />
      </FormField>
      <ErrorLine error={error} />
    </AppModal>
  );
}

/** Wpłata z wyciągu bez pewnego dopasowania: wybór faktury albo pominięcie z powodem. */
export function CreditDialog({ credit, onClose }: { credit: SalesCredit; onClose: () => void }) {
  const { showToast } = useToast();
  const assign = useAssignCredit();
  const ignore = useIgnoreCredit();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const pick = (invoiceId: number) =>
    assign.mutate(
      { paymentId: credit.id, invoiceId },
      {
        onSuccess: () => {
          showToast("Wpłata przypisana do faktury", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się przypisać wpłaty.")),
      },
    );

  const skip = () => {
    if (reason.trim().length < 3) {
      setError("Napisz, czego dotyczy wpłata (co najmniej 3 znaki).");
      return;
    }
    ignore.mutate(
      { paymentId: credit.id, reason: reason.trim() },
      {
        onSuccess: () => {
          showToast("Wpłata pominięta", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się pominąć wpłaty.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`Wpłata ${formatMoney(credit.amount, credit.currency)}`}
      description={credit.title || "Bez tytułu przelewu"}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Zamknij
          </Button>
          <Button variant="outline" onClick={skip} disabled={ignore.isPending}>
            Pomiń wpłatę
          </Button>
        </>
      }
    >
      {credit.hints.length ? (
        <ul className="space-y-1.5">
          {credit.hints.map((hint) => (
            <li key={hint.invoice_id} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0">
                <span className="block truncate">{hint.invoice_number}</span>
                <span className="block text-xs text-muted-foreground">
                  {hint.client_name ?? "—"} · do zapłaty {formatMoney(hint.to_pay, hint.currency)}
                </span>
              </span>
              <Button size="sm" onClick={() => pick(hint.invoice_id)} disabled={assign.isPending}>
                To ta faktura
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          Żadna otwarta faktura nie ma tej kwoty do zapłaty.
        </p>
      )}
      <FormField label="Powód pominięcia" htmlFor="sales-credit-reason" className="mt-4">
        <Textarea
          id="sales-credit-reason"
          value={reason}
          maxLength={500}
          rows={2}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Np. zwrot kaucji, nie zapłata faktury."
        />
      </FormField>
      <ErrorLine error={error} />
    </AppModal>
  );
}
