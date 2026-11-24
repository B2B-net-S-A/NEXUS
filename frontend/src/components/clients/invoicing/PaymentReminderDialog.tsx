"use client";

import { useEffect, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { useReminderDraft, useSendReminder, type ReminderDraft } from "@/lib/api/client-invoicing";
import { formatDayMonthPl, formatMomentPl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";

import { reminderLevelText } from "./invoicing-format";

/**
 * „Przygotuj monit” (Finanse → Po terminie): szkic maila do klienta o fakturach
 * po terminie z dowodem z wyciągów. Nic nie wychodzi bez kliknięcia „Wyślij”
 * i potwierdzenia; adresaci tylko z kontaktów rozliczeniowych klienta.
 */
export function PaymentReminderDialog({ clientId, onClose }: { clientId: number; onClose: () => void }) {
  const [language, setLanguage] = useState<"pl" | "en" | null>(null);
  const draft = useReminderDraft(clientId, language);

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`Monit płatności${draft.data?.client_name ? ` · ${draft.data.client_name}` : ""}`}
      description="Szkic maila do klienta. Wyślesz go dopiero przyciskiem na dole — nic nie wychodzi samo."
      size="lg"
    >
      {draft.isError ? (
        <QueryStateNotice state="error" onRetry={() => draft.refetch()} />
      ) : draft.isSuccess ? (
        <ReminderForm
          key={`${draft.data.language}-${draft.data.subject}`}
          draft={draft.data}
          onLanguage={setLanguage}
          onClose={onClose}
        />
      ) : (
        <p className="py-6 text-sm text-muted-foreground">Przygotowuję szkic…</p>
      )}
    </AppModal>
  );
}

function ReminderForm({
  draft,
  onLanguage,
  onClose,
}: {
  draft: ReminderDraft;
  onLanguage: (language: "pl" | "en") => void;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const send = useSendReminder();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [to, setTo] = useState<string[]>(() => draft.recipients.slice(0, 1).map((r) => r.email));
  const [subject, setSubject] = useState(draft.subject);
  const [text, setText] = useState(draft.text);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setError(null), [to, subject, text]);

  if (!draft.invoices.length) {
    return (
      <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
        Klient nie ma faktur po terminie z dowodem z wyciągów — monitu nie ma o czym wysłać.
      </p>
    );
  }

  const toggle = (email: string, checked: boolean) =>
    setTo((current) => (checked ? [...current, email] : current.filter((item) => item !== email)));

  const submit = async () => {
    if (!to.length) {
      setError("Zaznacz co najmniej jednego adresata.");
      return;
    }
    const ok = await askConfirm({
      title: "Wysłać monit do klienta?",
      description: `Mail „${subject}” pójdzie do: ${to.join(", ")}. Odpowiedź klienta trafi na Twoją skrzynkę.`,
      confirmLabel: "Wyślij monit",
    });
    if (!ok) return;
    send.mutate(
      { client_id: draft.client_id, to, subject, text },
      {
        onSuccess: (result) => {
          if (result.sent === 0) {
            setError("Poczta NEXUSA nie potwierdziła wysyłki — monit nie wyszedł. Spróbuj później.");
            return;
          }
          showToast(
            result.failed
              ? `Monit wysłany do ${result.sent}, nie wyszedł do ${result.failed}`
              : "Monit wysłany",
            result.failed ? "info" : "success",
          );
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się wysłać monitu.")),
      },
    );
  };

  return (
    <div className="grid gap-4" data-testid="payment-reminder-form">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <span className="font-medium">
          {draft.level ? draft.level_label : `Monit od ${draft.first_day}. dnia po terminie`}
        </span>
        <span className="text-muted-foreground">
          {countPl(draft.invoices.length, "faktura", "faktury", "faktur")}
          {draft.totals.length
            ? ` · ${draft.totals.map((t) => formatMoney(t.amount, t.currency)).join(", ")}`
            : ""}
        </span>
        {draft.last_sent_at ? (
          <span className="text-muted-foreground">
            · ostatni monit {formatMomentPl(draft.last_sent_at)}
            {draft.last_level ? ` (${reminderLevelText(draft.last_level)})` : ""}
          </span>
        ) : null}
        <span className="ml-auto flex gap-1">
          {(["pl", "en"] as const).map((language) => (
            <Button
              key={language}
              size="sm"
              variant={draft.language === language ? "secondary" : "ghost"}
              onClick={() => onLanguage(language)}
            >
              {language === "pl" ? "Polski" : "English"}
            </Button>
          ))}
        </span>
      </div>

      <ul className="grid gap-1 text-xs text-muted-foreground">
        {draft.invoices.map((invoice) => (
          <li key={invoice.invoice_id} className="flex flex-wrap gap-x-2">
            <span className="font-medium text-foreground">{invoice.invoice_number}</span>
            <span>termin {invoice.due_date ? formatDayMonthPl(invoice.due_date) : "—"}</span>
            <span>
              {invoice.vat
                ? `VAT w PLN ${invoice.vat_pln ? formatMoney(invoice.vat_pln, "PLN") : "bez kursu"}`
                : formatMoney(invoice.to_pay, invoice.currency)}
            </span>
            <span>{countPl(invoice.overdue_days, "dzień", "dni", "dni")} po terminie</span>
          </li>
        ))}
      </ul>

      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">Do kogo</legend>
        {draft.recipients.length ? (
          draft.recipients.map((recipient) => (
            <label key={recipient.email} className="flex items-start gap-2 text-sm">
              <Checkbox
                checked={to.includes(recipient.email)}
                onCheckedChange={(checked) => toggle(recipient.email, checked === true)}
                aria-label={recipient.email}
              />
              <span>
                {recipient.name ? `${recipient.name} · ` : ""}
                {recipient.email}
                <span className="block text-xs text-muted-foreground">{recipient.source_label}</span>
              </span>
            </label>
          ))
        ) : (
          <p className="rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
            Klient nie ma kontaktu rozliczeniowego. Dodaj w profilu klienta kontakt z działem „Finanse”
            (albo adres paczki w regułach rozliczeń) i wróć tutaj.
          </p>
        )}
      </fieldset>

      <FormField label="Temat" htmlFor="reminder-subject">
        <Input id="reminder-subject" value={subject} onChange={(event) => setSubject(event.target.value)} />
      </FormField>
      <FormField label="Treść" htmlFor="reminder-text">
        <Textarea
          id="reminder-text"
          rows={14}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="font-mono text-xs"
        />
      </FormField>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Zamknij
        </Button>
        <Button onClick={submit} disabled={send.isPending || !draft.level || !draft.recipients.length}>
          {send.isPending ? "Wysyłanie…" : "Wyślij monit"}
        </Button>
      </div>
      {confirmDialog}
    </div>
  );
}
