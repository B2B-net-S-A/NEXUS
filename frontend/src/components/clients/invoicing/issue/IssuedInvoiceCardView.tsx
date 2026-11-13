"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  Download,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  X,
} from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadIssuedFile,
  issuedPaths,
  useCheckIssued,
  useCreateCorrection,
  useDeleteIssued,
  useIssueSettings,
  useIssuedCard,
  useSendIssued,
  useUpdateIssued,
  type IssueBuyer,
  type IssueLine,
  type IssuedInvoiceCard,
  type InvoicePatch,
} from "@/lib/api/issued-invoices";
import { formatDayMonthPl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";

import {
  STATUS_TONE,
  apiDecimal,
  invoiceSteps,
  previewNet,
  sendDisabledReason,
  type InvoiceStep,
} from "./issue-format";

const SELECT =
  "h-9 w-full rounded-md border border-border bg-card px-2 text-sm text-foreground";
const EMPTY_LINE: IssueLine = {
  name: "",
  consultant: null,
  quantity: "1",
  unit: "usł.",
  unit_price: null,
  vat_rate: null,
  net: null,
  order_id: null,
};

interface FormState {
  issue_date: string;
  period_from: string;
  period_to: string;
  sale_date: string;
  due_date: string;
  client_order_number: string;
  notes: string;
  correction_reason: string;
  currency: IssuedInvoiceCard["currency"];
  series_code: "PL" | "UE";
  buyer: IssueBuyer;
  lines: IssueLine[];
}

function formFrom(card: IssuedInvoiceCard): FormState {
  return {
    issue_date: card.issue_date,
    period_from: card.period_from ?? "",
    period_to: card.period_to ?? "",
    sale_date: card.sale_date ?? "",
    due_date: card.due_date ?? "",
    client_order_number: card.client_order_number ?? "",
    notes: card.notes ?? "",
    correction_reason: card.correction_reason ?? "",
    currency: card.currency,
    series_code: card.series_code === "UE" ? "UE" : "PL",
    buyer: {
      name: card.buyer.name ?? "",
      number: card.buyer.number ?? "",
      address_l1: card.buyer.address_l1 ?? "",
      address_l2: card.buyer.address_l2 ?? "",
      country: card.buyer.country ?? "PL",
    },
    lines: card.lines.map((line) => ({ ...line })),
  };
}

function patchFrom(card: IssuedInvoiceCard, form: FormState): InvoicePatch {
  const patch: InvoicePatch = {
    issue_date: form.issue_date,
    sale_date: form.sale_date || null,
    period_from: form.period_from || null,
    period_to: form.period_to || null,
    due_date: form.due_date || null,
    client_order_number: form.client_order_number || null,
    notes: form.notes || null,
    buyer: form.buyer,
    lines: form.lines.map((line) => ({
      ...line,
      quantity: apiDecimal(line.quantity),
      unit_price: apiDecimal(line.unit_price),
    })),
  };
  if (card.invoice_type === "KOR")
    patch.correction_reason = form.correction_reason || null;
  else patch.currency = form.currency;
  if (card.invoice_type === "VAT") patch.series_code = form.series_code;
  return patch;
}

/**
 * Karta faktury wystawianej w NEXUSIE (M5): kroki Szkic → Wyślij do KSeF →
 * Przyjęta (numer KSeF) → UPO → Zapłacona, edycja szkicu, wysyłka
 * z potwierdzeniem, pliki, korekta.
 */
export function IssuedInvoiceCardView({ invoiceId }: { invoiceId: number }) {
  const query = useIssuedCard(invoiceId);
  const settings = useIssueSettings(null, query.isSuccess);

  if (query.isLoading)
    return (
      <p className="py-6 text-sm text-muted-foreground">Wczytywanie faktury…</p>
    );
  if (query.isError || !query.data) {
    return <QueryStateNotice state="error" onRetry={() => query.refetch()} />;
  }
  return (
    <CardBody
      key={`${query.data.id}-${query.data.status}`}
      card={query.data}
      vatRates={settings.data?.vat_rates ?? []}
      ksefReason={settings.data?.ksef.disabled_reason ?? null}
    />
  );
}

function CardBody({
  card,
  vatRates,
  ksefReason,
}: {
  card: IssuedInvoiceCard;
  vatRates: { code: string; label: string }[];
  ksefReason: string | null;
}) {
  const { showToast } = useToast();
  const router = useRouter();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const update = useUpdateIssued(card.id);
  const send = useSendIssued();
  const check = useCheckIssued();
  const remove = useDeleteIssued();
  const [form, setForm] = useState<FormState>(() => formFrom(card));
  const [dirty, setDirty] = useState(false);
  const [correction, setCorrection] = useState(false);

  useEffect(() => {
    if (!dirty) setForm(formFrom(card));
  }, [card, dirty]);

  const change = (next: Partial<FormState>) => {
    setForm((current) => ({ ...current, ...next }));
    setDirty(true);
  };
  const changeLine = (index: number, next: Partial<IssueLine>) =>
    change({
      lines: form.lines.map((line, i) =>
        i === index ? { ...line, ...next } : line,
      ),
    });

  const saveForm = (onSaved?: () => void) =>
    update.mutate(patchFrom(card, form), {
      onSuccess: () => {
        setDirty(false);
        showToast("Zapisano szkic", "success");
        onSaved?.();
      },
      onError: (err) =>
        showToast(
          apiErrorMessage(err, "Nie udało się zapisać szkicu."),
          "error",
        ),
    });

  const doSend = async () => {
    const ok = await askConfirm({
      title: "Wysłać fakturę do KSeF?",
      description: card.invoice_number
        ? `Faktura ${card.invoice_number} idzie do KSeF ponownie, z tym samym numerem. Po przyjęciu nie da się jej zmienić — tylko skorygować.`
        : "Faktura dostanie teraz kolejny numer z serii i trafi do KSeF. Po przyjęciu nie da się jej zmienić — tylko skorygować.",
      confirmLabel: "Wyślij do KSeF",
    });
    if (!ok) return;
    send.mutate(card.id, {
      onSuccess: (result) =>
        showToast(
          result.status === "accepted"
            ? `Przyjęta w KSeF: ${result.invoice_number}`
            : `${result.status_label}${result.ksef_status_text ? ` — ${result.ksef_status_text}` : ""}`,
          result.status === "accepted" ? "success" : "error",
        ),
      onError: (err) =>
        showToast(
          apiErrorMessage(err, "Nie udało się wysłać faktury."),
          "error",
        ),
    });
  };

  const doDelete = async () => {
    const numbered = card.invoice_number !== null;
    const ok = await askConfirm({
      title: numbered ? "Wycofać fakturę?" : "Usunąć szkic?",
      description: numbered
        ? `Faktura ${card.invoice_number} nie weszła do obrotu. Jeśli to ostatni numer serii, wróci do puli; inaczej zostanie ślad „numer niewykorzystany”.`
        : "Szkic nie ma numeru — usunięcie nie zostawi dziury w numeracji.",
      confirmLabel: numbered ? "Wycofaj fakturę" : "Usuń szkic",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(card.id, {
      onSuccess: (result) => {
        showToast(
          result.result === "deleted"
            ? "Usunięto"
            : "Wycofano — numer zostaje jako ślad",
          "success",
        );
        if (result.result === "deleted")
          router.push("/finance?view=sales-invoices");
      },
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się usunąć."), "error"),
    });
  };

  const download = async (path: string, name: string) => {
    try {
      await downloadIssuedFile(path, name);
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
    }
  };

  const steps = invoiceSteps(card);
  const disabledReason = sendDisabledReason(card, ksefReason);
  const editable = card.editable;
  const stem = (card.invoice_number ?? `szkic-${card.id}`).replace(/\//g, "-");

  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-foreground">
            {card.type_label} {card.invoice_number ?? "— szkic"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {card.client_name ?? card.buyer.name}
            {card.period ? ` · usługi za ${card.period}` : ""}
            {card.corrects
              ? ` · korekta faktury ${card.corrects.invoice_number}`
              : ""}
          </p>
          <StatusDot tone={STATUS_TONE[card.status]} className="mt-1">
            {card.status_label}
          </StatusDot>
          {card.ksef_status_text ? (
            <p className="mt-1 max-w-3xl text-xs text-muted-foreground">
              {card.ksef_status_text}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {editable ? (
            <Button
              size="sm"
              onClick={doSend}
              disabled={!card.can_send || dirty || send.isPending}
              title={
                dirty
                  ? "Najpierw zapisz zmiany."
                  : (disabledReason ?? undefined)
              }
            >
              <Send className="h-4 w-4" aria-hidden />
              {send.isPending ? "Wysyłanie…" : "Wyślij do KSeF"}
            </Button>
          ) : null}
          {card.can_check ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                check.mutate(card.id, {
                  onError: (err) =>
                    showToast(
                      apiErrorMessage(err, "Nie udało się sprawdzić statusu."),
                      "error",
                    ),
                })
              }
              disabled={check.isPending}
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              Sprawdź status
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              download(issuedPaths.pdf(card.id), `faktura-${stem}.pdf`)
            }
          >
            <Download className="h-4 w-4" aria-hidden />
            PDF
          </Button>
          {card.has_upo ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                download(issuedPaths.upo(card.id), `upo-${stem}.xml`)
              }
            >
              UPO
            </Button>
          ) : null}
          {card.has_xml ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                download(issuedPaths.xml(card.id), `fa3-${stem}.xml`)
              }
            >
              XML
            </Button>
          ) : null}
          {card.can_correct ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setCorrection(true)}
            >
              Wystaw korektę
            </Button>
          ) : null}
          {editable ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={doDelete}
              disabled={remove.isPending}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              {card.invoice_number ? "Wycofaj" : "Usuń szkic"}
            </Button>
          ) : null}
        </div>
      </header>

      <Steps steps={steps} />

      {editable && disabledReason ? (
        <section
          className="rounded-lg border border-border bg-muted/50 px-4 py-2 text-sm"
          aria-label="Przed wysyłką"
        >
          {card.problems.length ? (
            <ul className="list-disc pl-5 text-muted-foreground">
              {card.problems.map((problem) => (
                <li key={problem}>{problem}</li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground">{disabledReason}</p>
          )}
        </section>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <section
          className="space-y-3 rounded-lg border border-border bg-card px-4 py-3"
          aria-label="Dane faktury"
        >
          <div className="grid gap-3 md:grid-cols-4">
            <FormField label="Data wystawienia" htmlFor="inv-issue">
              <Input
                id="inv-issue"
                type="date"
                disabled={!editable}
                value={form.issue_date}
                onChange={(e) => change({ issue_date: e.target.value })}
              />
            </FormField>
            {card.invoice_type === "ZAL" ? (
              <FormField label="Otrzymanie zaliczki" htmlFor="inv-sale">
                <Input
                  id="inv-sale"
                  type="date"
                  disabled={!editable}
                  value={form.sale_date}
                  onChange={(e) => change({ sale_date: e.target.value })}
                />
              </FormField>
            ) : (
              <>
                <FormField label="Okres od" htmlFor="inv-from">
                  <Input
                    id="inv-from"
                    type="date"
                    disabled={!editable}
                    value={form.period_from}
                    onChange={(e) => change({ period_from: e.target.value })}
                  />
                </FormField>
                <FormField label="Okres do" htmlFor="inv-to">
                  <Input
                    id="inv-to"
                    type="date"
                    disabled={!editable}
                    value={form.period_to}
                    onChange={(e) => change({ period_to: e.target.value })}
                  />
                </FormField>
              </>
            )}
            <FormField label="Termin płatności" htmlFor="inv-due">
              <Input
                id="inv-due"
                type="date"
                disabled={!editable}
                value={form.due_date}
                onChange={(e) => change({ due_date: e.target.value })}
              />
            </FormField>
          </div>
          <div className="grid gap-3 md:grid-cols-4">
            <FormField
              label="Numer zamówienia klienta"
              htmlFor="inv-order"
              className="md:col-span-2"
            >
              <Input
                id="inv-order"
                disabled={!editable}
                value={form.client_order_number}
                onChange={(e) =>
                  change({ client_order_number: e.target.value })
                }
              />
            </FormField>
            <FormField label="Waluta" htmlFor="inv-currency">
              <select
                id="inv-currency"
                className={SELECT}
                disabled={!editable || card.invoice_type === "KOR"}
                value={form.currency}
                onChange={(e) =>
                  change({ currency: e.target.value as FormState["currency"] })
                }
              >
                <option value="PLN">PLN</option>
                <option value="EUR">EUR</option>
                <option value="USD">USD</option>
              </select>
            </FormField>
            {card.invoice_type === "VAT" ? (
              <FormField label="Seria" htmlFor="inv-series">
                <select
                  id="inv-series"
                  className={SELECT}
                  disabled={!editable || card.invoice_number !== null}
                  value={form.series_code}
                  onChange={(e) =>
                    change({ series_code: e.target.value as "PL" | "UE" })
                  }
                >
                  <option value="PL">krajowa</option>
                  <option value="UE">nabywca z UE</option>
                </select>
              </FormField>
            ) : null}
          </div>
          {card.invoice_type === "KOR" ? (
            <FormField label="Przyczyna korekty" htmlFor="inv-reason">
              <Input
                id="inv-reason"
                disabled={!editable}
                value={form.correction_reason}
                onChange={(e) => change({ correction_reason: e.target.value })}
              />
            </FormField>
          ) : null}

          {card.lines_before.length ? (
            <div>
              <h3 className="mb-1 text-sm font-semibold text-foreground">
                Stan przed korektą
              </h3>
              <ul className="text-sm text-muted-foreground">
                {card.lines_before.map((line, index) => (
                  <li key={index} className="flex justify-between gap-3">
                    <span className="truncate">{line.name}</span>
                    <span className="shrink-0 tabular-nums">
                      {line.quantity} × {line.unit_price} ={" "}
                      {formatMoney(line.net ?? "0", card.currency)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <LinesEditor
            lines={form.lines}
            currency={form.currency}
            vatRates={vatRates}
            editable={editable}
            onChange={changeLine}
            onAdd={() =>
              change({
                lines: [
                  ...form.lines,
                  { ...EMPTY_LINE, vat_rate: form.lines[0]?.vat_rate ?? null },
                ],
              })
            }
            onRemove={(index) =>
              change({ lines: form.lines.filter((_, i) => i !== index) })
            }
            title={card.invoice_type === "KOR" ? "Stan po korekcie" : "Pozycje"}
          />

          <FormField label="Uwagi na fakturze" htmlFor="inv-notes">
            <Textarea
              id="inv-notes"
              rows={2}
              maxLength={1000}
              disabled={!editable}
              value={form.notes}
              onChange={(e) => change({ notes: e.target.value })}
            />
          </FormField>

          {editable ? (
            <div className="flex justify-end gap-2">
              {dirty ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setForm(formFrom(card));
                    setDirty(false);
                  }}
                >
                  Odrzuć zmiany
                </Button>
              ) : null}
              <Button
                size="sm"
                onClick={() => saveForm()}
                disabled={!dirty || update.isPending}
              >
                {update.isPending ? "Zapisywanie…" : "Zapisz szkic"}
              </Button>
            </div>
          ) : null}
        </section>

        <aside className="space-y-3">
          <section
            className="rounded-lg border border-border bg-card px-4 py-3"
            aria-label="Nabywca"
          >
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              Nabywca
            </h3>
            <div className="space-y-2">
              <Input
                aria-label="Nazwa nabywcy"
                disabled={!editable}
                value={form.buyer.name}
                onChange={(e) =>
                  change({ buyer: { ...form.buyer, name: e.target.value } })
                }
              />
              <Input
                aria-label="NIP albo VAT UE nabywcy"
                disabled={!editable}
                value={form.buyer.number}
                onChange={(e) =>
                  change({ buyer: { ...form.buyer, number: e.target.value } })
                }
                placeholder="NIP albo VAT UE (np. FI12345678)"
              />
              <Input
                aria-label="Adres nabywcy"
                disabled={!editable}
                value={form.buyer.address_l1}
                onChange={(e) =>
                  change({
                    buyer: { ...form.buyer, address_l1: e.target.value },
                  })
                }
                placeholder="Ulica, kod, miasto"
              />
              <Input
                aria-label="Kraj nabywcy"
                disabled={!editable}
                value={form.buyer.country}
                maxLength={2}
                onChange={(e) =>
                  change({
                    buyer: {
                      ...form.buyer,
                      country: e.target.value.toUpperCase(),
                    },
                  })
                }
                placeholder="PL"
              />
            </div>
          </section>
          <section
            className="rounded-lg border border-border bg-card px-4 py-3"
            aria-label="Kwoty"
          >
            <h3 className="mb-2 text-sm font-semibold text-foreground">
              Kwoty{card.invoice_type === "KOR" ? " (różnica)" : ""}
            </h3>
            <dl className="space-y-1 text-sm">
              {card.rates.map((rate) => (
                <div
                  key={rate.code}
                  className="flex justify-between gap-2 text-muted-foreground"
                >
                  <dt>{rate.label}</dt>
                  <dd className="tabular-nums">
                    {formatMoney(rate.net, card.currency)}
                    {rate.vat !== "0.00"
                      ? ` + ${formatMoney(rate.vat, card.currency)}`
                      : ""}
                  </dd>
                </div>
              ))}
              <div className="flex justify-between gap-2 border-t border-border pt-1 font-semibold text-foreground">
                <dt>Brutto</dt>
                <dd className="tabular-nums">
                  {formatMoney(card.gross, card.currency)}
                </dd>
              </div>
            </dl>
            {card.fx ? (
              <p className="mt-2 text-xs text-muted-foreground">
                Kurs NBP {card.currency} z {formatDayMonthPl(card.fx.date)}:{" "}
                {card.fx.rate} zł
              </p>
            ) : card.currency !== "PLN" ? (
              <p className="mt-2 text-xs text-destructive">
                Brak kursu NBP z dnia przed datą dostawy.
              </p>
            ) : null}
          </section>
          {card.ksef_number ? (
            <section
              className="rounded-lg border border-border bg-card px-4 py-3 text-sm"
              aria-label="KSeF"
            >
              <h3 className="mb-1 text-sm font-semibold text-foreground">
                KSeF
              </h3>
              <p className="break-all text-foreground">{card.ksef_number}</p>
              {card.ksef_environment === "test" ? (
                <p className="text-xs text-muted-foreground">
                  środowisko testowe MF
                </p>
              ) : null}
            </section>
          ) : null}
        </aside>
      </div>

      {correction ? (
        <CorrectionDialog card={card} onClose={() => setCorrection(false)} />
      ) : null}
      {confirmDialog}
    </div>
  );
}

function Steps({ steps }: { steps: InvoiceStep[] }) {
  return (
    <ol
      className="grid grid-cols-5 gap-1 rounded-lg border border-border bg-card px-2 py-2"
      aria-label="Kroki faktury"
    >
      {steps.map((step) => (
        <li
          key={step.key}
          aria-current={step.state === "current" ? "step" : undefined}
          className={cn(
            "flex min-w-0 items-start gap-2 rounded-md px-2 py-1",
            step.state === "current" && "bg-muted",
          )}
        >
          <span
            aria-hidden
            className={cn(
              "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-xs",
              step.state === "done" &&
                "border-success bg-success text-success-foreground",
              step.state === "failed" && "border-destructive text-destructive",
              step.state === "current" && "border-primary text-primary",
              step.state === "todo" && "border-border text-muted-foreground",
            )}
          >
            {step.state === "done" ? (
              <Check className="h-3 w-3" />
            ) : step.state === "failed" ? (
              <X className="h-3 w-3" />
            ) : null}
          </span>
          <span className="min-w-0">
            <span className="block truncate text-sm text-foreground">
              {step.label}
            </span>
            {step.detail ? (
              <span
                className="block truncate text-xs text-muted-foreground"
                title={step.detail}
              >
                {step.detail}
              </span>
            ) : null}
          </span>
        </li>
      ))}
    </ol>
  );
}

function LinesEditor({
  lines,
  currency,
  vatRates,
  editable,
  onChange,
  onAdd,
  onRemove,
  title,
}: {
  lines: IssueLine[];
  currency: string;
  vatRates: { code: string; label: string }[];
  editable: boolean;
  onChange: (index: number, next: Partial<IssueLine>) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
  title: string;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {editable ? (
          <Button size="sm" variant="ghost" onClick={onAdd}>
            <Plus className="h-4 w-4" aria-hidden />
            Pozycja
          </Button>
        ) : null}
      </div>
      <ul className="space-y-2">
        {lines.map((line, index) => {
          const net = previewNet(line);
          return (
            <li
              key={index}
              className="grid gap-2 rounded-md border border-border/60 p-2 md:grid-cols-[5rem_4.5rem_7rem_7rem_minmax(0,1fr)_2.25rem]"
            >
              {/* Nazwa w osobnej linii: przy 1280 px w jednym rzędzie z liczbami
                  zostawało jej ok. 100 px i widać było tylko „Usługi”. */}
              <Input
                aria-label={`Nazwa pozycji ${index + 1}`}
                className="md:col-span-6"
                disabled={!editable}
                value={line.name}
                title={line.name}
                onChange={(e) => onChange(index, { name: e.target.value })}
              />
              <Input
                aria-label={`Ilość — pozycja ${index + 1}`}
                inputMode="decimal"
                disabled={!editable}
                value={line.quantity ?? ""}
                onChange={(e) => onChange(index, { quantity: e.target.value })}
              />
              <Input
                aria-label={`Jednostka — pozycja ${index + 1}`}
                disabled={!editable}
                value={line.unit ?? ""}
                onChange={(e) => onChange(index, { unit: e.target.value })}
              />
              <Input
                aria-label={`Cena netto — pozycja ${index + 1}`}
                inputMode="decimal"
                disabled={!editable}
                value={line.unit_price ?? ""}
                placeholder="cena"
                onChange={(e) =>
                  onChange(index, { unit_price: e.target.value })
                }
              />
              <select
                aria-label={`Stawka VAT — pozycja ${index + 1}`}
                className={SELECT}
                disabled={!editable}
                value={line.vat_rate ?? ""}
                onChange={(e) =>
                  onChange(index, { vat_rate: e.target.value || null })
                }
              >
                <option value="">stawka…</option>
                {vatRates.map((rate) => (
                  <option key={rate.code} value={rate.code}>
                    {rate.label}
                  </option>
                ))}
              </select>
              <span className="self-center text-right text-sm tabular-nums text-foreground">
                {net ? formatMoney(net, currency) : "—"}
              </span>
              {editable ? (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Usuń pozycję ${index + 1}`}
                  onClick={() => onRemove(index)}
                >
                  <X className="h-4 w-4" aria-hidden />
                </Button>
              ) : (
                <span />
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function CorrectionDialog({
  card,
  onClose,
}: {
  card: IssuedInvoiceCard;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const router = useRouter();
  const create = useCreateCorrection();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (reason.trim().length < 3) {
      setError("Podaj przyczynę korekty (co najmniej 3 znaki).");
      return;
    }
    create.mutate(
      { id: card.id, reason: reason.trim() },
      {
        onSuccess: (created) => {
          showToast("Utworzono szkic korekty", "success");
          onClose();
          router.push(`/finance/faktury/${created.id}`);
        },
        onError: (err) =>
          setError(apiErrorMessage(err, "Nie udało się utworzyć korekty.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={`Korekta faktury ${card.invoice_number}`}
      description="Powstanie szkic korekty z pozycjami faktury — zmienisz w nim ilości albo ceny, różnicę policzy NEXUS."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={create.isPending}>
            {create.isPending ? "Tworzenie…" : "Utwórz szkic korekty"}
          </Button>
        </>
      }
    >
      <FormField label="Przyczyna korekty" htmlFor="correction-reason">
        <Input
          id="correction-reason"
          maxLength={256}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
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
