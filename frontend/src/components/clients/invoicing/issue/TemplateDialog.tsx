"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDeleteTemplate,
  useIssueSettings,
  useSaveTemplate,
  type BenefitKind,
  type InvoiceTemplate,
  type IssueBuyer,
  type IssueCurrency,
  type IssueLine,
  type TemplateKind,
} from "@/lib/api/issued-invoices";

const SELECT =
  "h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground";
const EMPTY_BUYER: IssueBuyer = { name: "", number: "", address_l1: "", address_l2: "", country: "PL" };

type DraftLine = Pick<IssueLine, "name" | "quantity" | "unit" | "unit_price" | "vat_rate">;

function blankLine(vat: string): DraftLine {
  return { name: "", quantity: "1", unit: "usł.", unit_price: "", vat_rate: vat };
}

/**
 * Szablon faktury „co miesiąc” (E6): nabywca, pozycje, ważność. W nazwie
 * pozycji `{okres}` daje „październik 2026”, `{okresu}` „października 2026”,
 * `{mm}` i `{rrrr}` — miesiąc, za który powstaje szkic.
 */
export function TemplateDialog({
  template,
  defaultKind,
  onClose,
}: {
  template: InvoiceTemplate | null;
  defaultKind: TemplateKind;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const settings = useIssueSettings();
  const save = useSaveTemplate(template?.id ?? null);
  const remove = useDeleteTemplate();
  const vatRates = settings.data?.vat_rates ?? [];
  const defaultVat = settings.data?.settings.default_vat ?? "23";
  const [kind, setKind] = useState<TemplateKind>(template?.kind ?? defaultKind);
  const [benefit, setBenefit] = useState<BenefitKind>(template?.benefit ?? "sport");
  const [name, setName] = useState(template?.name ?? "");
  const [buyer, setBuyer] = useState<IssueBuyer>(template?.buyer ?? EMPTY_BUYER);
  const [currency, setCurrency] = useState<IssueCurrency>(template?.currency ?? "PLN");
  const [lines, setLines] = useState<DraftLine[]>(
    template?.lines.length ? template.lines : [blankLine(defaultVat)],
  );
  // Ustawienia mogą dojść po otwarciu okna: pozycje nowego szablonu ze stawką
  // przyjętą na start dostają wtedy default_vat z ustawień.
  const [vatSeed, setVatSeed] = useState(defaultVat);
  if (!template?.lines.length && vatSeed !== defaultVat) {
    setVatSeed(defaultVat);
    setLines((current) =>
      current.map((line) => (line.vat_rate === vatSeed ? { ...line, vat_rate: defaultVat } : line)),
    );
  }
  const [validFrom, setValidFrom] = useState(template?.valid_from ?? "");
  const [validTo, setValidTo] = useState(template?.valid_to ?? "");
  const [paymentDays, setPaymentDays] = useState(
    template?.payment_days === null || template?.payment_days === undefined ? "" : String(template.payment_days),
  );
  const [active, setActive] = useState(template?.active ?? true);
  const [notes, setNotes] = useState(template?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  const setLine = (index: number, patch: Partial<DraftLine>) =>
    setLines((current) => current.map((line, at) => (at === index ? { ...line, ...patch } : line)));

  const submit = () => {
    save.mutate(
      {
        kind,
        benefit: kind === "benefit" ? benefit : null,
        name,
        buyer,
        currency,
        lines,
        valid_from: validFrom || null,
        valid_to: validTo || null,
        payment_days: paymentDays === "" ? null : Number(paymentDays),
        active,
        notes: notes || null,
      },
      {
        onSuccess: () => {
          showToast(template ? "Zapisano szablon" : "Dodano szablon", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać szablonu.")),
      },
    );
  };

  const drop = async () => {
    if (!template) return;
    const ok = await askConfirm({
      title: "Usunąć szablon?",
      description:
        "Faktury już wystawione z szablonu zostają. Zamiast usuwać możesz szablon wyłączyć — zostanie na liście.",
      confirmLabel: "Usuń szablon",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(template.id, {
      onSuccess: () => {
        showToast("Usunięto szablon", "success");
        onClose();
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się usunąć szablonu.")),
    });
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={template ? "Szablon faktury" : "Nowy szablon faktury"}
      description="Co miesiąc z szablonu powstaje szkic do sprawdzenia i wysyłki do KSeF."
      size="xl"
      footer={
        <>
          {template ? (
            <Button variant="ghost" className="mr-auto text-destructive" onClick={drop} disabled={remove.isPending}>
              <Trash2 className="h-4 w-4" aria-hidden />
              Usuń
            </Button>
          ) : null}
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-4">
          <FormField label="Rodzaj" htmlFor="template-kind">
            <select
              id="template-kind"
              className={SELECT}
              value={kind}
              onChange={(event) => setKind(event.target.value as TemplateKind)}
            >
              <option value="service">usługi</option>
              <option value="benefit">refaktura benefitu</option>
            </select>
          </FormField>
          {kind === "benefit" ? (
            <FormField label="Benefit" htmlFor="template-benefit">
              <select
                id="template-benefit"
                className={SELECT}
                value={benefit}
                onChange={(event) => setBenefit(event.target.value as BenefitKind)}
              >
                <option value="sport">pakiet sportowy</option>
                <option value="medical">opieka medyczna</option>
                <option value="other">inny</option>
              </select>
            </FormField>
          ) : null}
          <FormField label="Nazwa szablonu" htmlFor="template-name" className={kind === "benefit" ? "sm:col-span-2" : "sm:col-span-3"}>
            <Input
              id="template-name"
              value={name}
              placeholder="np. nazwa nabywcy"
              onChange={(event) => setName(event.target.value)}
            />
          </FormField>
        </div>

        <fieldset className="grid gap-3 rounded-lg border border-border p-3 sm:grid-cols-4">
          <legend className="px-1 text-sm font-medium text-foreground">Nabywca</legend>
          <FormField label="Nazwa" htmlFor="template-buyer-name" className="sm:col-span-2">
            <Input
              id="template-buyer-name"
              value={buyer.name}
              onChange={(event) => setBuyer({ ...buyer, name: event.target.value })}
            />
          </FormField>
          <FormField label="NIP albo VAT UE" htmlFor="template-buyer-number">
            <Input
              id="template-buyer-number"
              value={buyer.number}
              onChange={(event) => setBuyer({ ...buyer, number: event.target.value })}
            />
          </FormField>
          <FormField label="Waluta" htmlFor="template-currency">
            <select
              id="template-currency"
              className={SELECT}
              value={currency}
              onChange={(event) => setCurrency(event.target.value as IssueCurrency)}
            >
              <option value="PLN">PLN</option>
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
            </select>
          </FormField>
          <FormField label="Adres (ulica)" htmlFor="template-buyer-address" className="sm:col-span-2">
            <Input
              id="template-buyer-address"
              value={buyer.address_l1}
              placeholder="pusty = z kartoteki kontrahentów"
              onChange={(event) => setBuyer({ ...buyer, address_l1: event.target.value })}
            />
          </FormField>
          <FormField label="Kod i miejscowość" htmlFor="template-buyer-address2" className="sm:col-span-2">
            <Input
              id="template-buyer-address2"
              value={buyer.address_l2}
              onChange={(event) => setBuyer({ ...buyer, address_l2: event.target.value })}
            />
          </FormField>
        </fieldset>

        <fieldset className="grid gap-2 rounded-lg border border-border p-3">
          <legend className="px-1 text-sm font-medium text-foreground">Pozycje</legend>
          <p className="text-xs text-muted-foreground">
            W nazwie: {"{okres}"} = „październik 2026”, {"{okresu}"} = „października 2026”, {"{mm}"} i {"{rrrr}"} — miesiąc
            szkicu.
          </p>
          {lines.map((line, index) => (
            <div
              key={index}
              className="grid gap-2 md:grid-cols-[minmax(0,1fr)_5rem_5rem_7rem_6rem_2.25rem]"
              data-testid={`template-line-${index}`}
            >
              <Input
                aria-label={`Pozycja ${index + 1}: nazwa`}
                value={line.name}
                title={line.name}
                onChange={(event) => setLine(index, { name: event.target.value })}
              />
              <Input
                aria-label={`Pozycja ${index + 1}: ilość`}
                inputMode="decimal"
                value={line.quantity ?? ""}
                onChange={(event) => setLine(index, { quantity: event.target.value })}
              />
              <Input
                aria-label={`Pozycja ${index + 1}: jednostka`}
                value={line.unit ?? ""}
                onChange={(event) => setLine(index, { unit: event.target.value })}
              />
              <Input
                aria-label={`Pozycja ${index + 1}: cena netto`}
                inputMode="decimal"
                className="text-right tabular-nums"
                value={line.unit_price ?? ""}
                onChange={(event) => setLine(index, { unit_price: event.target.value })}
              />
              <select
                aria-label={`Pozycja ${index + 1}: stawka VAT`}
                className={SELECT}
                value={line.vat_rate ?? ""}
                onChange={(event) => setLine(index, { vat_rate: event.target.value })}
              >
                <option value="">—</option>
                {vatRates.map((rate) => (
                  <option key={rate.code} value={rate.code}>
                    {rate.label}
                  </option>
                ))}
              </select>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Usuń pozycję ${index + 1}`}
                disabled={lines.length === 1}
                onClick={() => setLines((current) => current.filter((_, at) => at !== index))}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          ))}
          <div>
            <Button size="sm" variant="outline" onClick={() => setLines((current) => [...current, blankLine(defaultVat)])}>
              <Plus className="h-4 w-4" aria-hidden />
              Dodaj pozycję
            </Button>
          </div>
        </fieldset>

        <div className="grid gap-3 sm:grid-cols-4">
          <FormField label="Obowiązuje od" htmlFor="template-from">
            <Input id="template-from" type="date" value={validFrom} onChange={(event) => setValidFrom(event.target.value)} />
          </FormField>
          <FormField label="Obowiązuje do" htmlFor="template-to">
            <Input id="template-to" type="date" value={validTo} onChange={(event) => setValidTo(event.target.value)} />
          </FormField>
          <FormField label="Termin płatności (dni)" htmlFor="template-days">
            <Input
              id="template-days"
              inputMode="numeric"
              placeholder="z ustawień"
              value={paymentDays}
              onChange={(event) => setPaymentDays(event.target.value.replace(/\D/g, "").slice(0, 3))}
            />
          </FormField>
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-foreground">
            <Checkbox checked={active} onCheckedChange={(value) => setActive(value === true)} aria-label="Szablon aktywny" />
            Aktywny
          </label>
        </div>
        <FormField label="Uwagi na fakturze" htmlFor="template-notes">
          <Input id="template-notes" value={notes} onChange={(event) => setNotes(event.target.value)} />
        </FormField>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {confirmDialog}
    </AppModal>
  );
}
