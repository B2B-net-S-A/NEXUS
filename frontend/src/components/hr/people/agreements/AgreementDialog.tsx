"use client";

import { useMemo, useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import { usePeople } from "@/lib/api/hr";
import {
  useAgreementTemplates,
  useCreateAgreement,
  useUpdateAgreement,
  type Agreement,
  type PersonAgreements,
} from "@/lib/api/hr-agreements";
import type { Currency } from "@/lib/api/hr-payroll";
import { employmentTerms } from "@/lib/hr-employment-terms";

import {
  afterSigning,
  draftInput,
  draftProblem,
  formatAmount,
  mandateMinimum,
  templateChoices,
  type DraftForm,
} from "./agreement-format";

const NONE = "none";
const CURRENCIES: Currency[] = ["PLN", "EUR", "USD"];

function initialForm(overview: PersonAgreements, agreement?: Agreement): DraftForm {
  if (agreement) {
    return {
      templateId: agreement.template ? String(agreement.template.template_id) : "",
      baseAgreementId: agreement.base_agreement_id ? String(agreement.base_agreement_id) : "",
      rate: formatAmount(agreement.hourly_rate).replace(/\s/g, ""),
      currency: agreement.currency,
      startDate: agreement.start_date,
      endDate: agreement.end_date ?? "",
      indefinite: agreement.end_date === null,
      agreementDate: agreement.agreement_date,
      hoursConfirmation: agreement.hours_confirmation,
      payoutDay: agreement.payout_day ? String(agreement.payout_day) : "",
      coordinatorId: agreement.coordinator_user_id ? String(agreement.coordinator_user_id) : "",
    };
  }
  const defaults = overview.defaults;
  return {
    templateId: "",
    baseAgreementId: defaults.base_agreement_id ? String(defaults.base_agreement_id) : "",
    rate: defaults.hourly_rate ? formatAmount(defaults.hourly_rate).replace(/\s/g, "") : "",
    currency: defaults.currency,
    startDate: "",
    endDate: "",
    indefinite: true,
    agreementDate: defaults.agreement_date,
    hoursConfirmation: defaults.hours_confirmation,
    payoutDay: String(defaults.payout_day),
    coordinatorId: defaults.coordinator_user_id ? String(defaults.coordinator_user_id) : "",
  };
}

/**
 * „Nowa umowa albo aneks” i poprawka szkicu (makieta „Umowa zlecenia”).
 * Wzór wybiera formę; aneks zmienia tylko stawkę od 1. dnia miesiąca.
 * Kontrole są te same co na serwerze (minimum zlecenia z Ustawień Płac,
 * art. 8b) — serwer i tak sprawdza je jeszcze raz.
 */
export function AgreementDialog({
  overview,
  agreement,
  onClose,
}: {
  overview: PersonAgreements;
  agreement?: Agreement;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const templates = useAgreementTemplates(true);
  const people = usePeople();
  const create = useCreateAgreement(overview.person.user_id);
  const update = useUpdateAgreement();
  const [form, setForm] = useState<DraftForm>(() => initialForm(overview, agreement));
  const [error, setError] = useState<string | null>(null);
  const userId = overview.person.user_id;
  const choices = useMemo(() => templateChoices(templates.data?.items ?? []), [templates.data]);
  const choice = choices.find((item) => String(item.templateId) === form.templateId);
  const kind = choice?.kind ?? agreement?.kind ?? "agreement";
  const signedBases = overview.agreements.filter(
    (row) => row.kind === "agreement" && row.status === "signed",
  );
  const base = signedBases.find((row) => String(row.id) === form.baseAgreementId);
  const employmentType =
    choice?.employmentType ??
    (kind === "annex" ? base?.employment_type ?? overview.person.employment_type : null) ??
    agreement?.employment_type ??
    overview.person.employment_type;
  const context = { kind, employmentType, minimumRates: overview.minimum_rates };
  const minimum = mandateMinimum(context, form);
  const words = employmentTerms(employmentType);
  const coordinators = (people.data?.items ?? []).filter((row) => row.user_id !== userId);
  const pending = create.isPending || update.isPending;
  const set = <K extends keyof DraftForm>(key: K, value: DraftForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const id = (name: string) => `agreement-${name}-${agreement?.id ?? "new"}`;

  const submit = () => {
    const problem = draftProblem(form, context);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    const input = draftInput(form, context);
    if (agreement && agreement.template?.template_id === input.template_id) {
      // Ten sam wzór — szkic zostaje przy swojej wersji pliku.
      delete input.template_id;
    }
    const done = (saved: Agreement) => {
      showToast(agreement ? "Szkic zapisany" : "Szkic umowy gotowy", "success");
      if (saved.warning) showToast(saved.warning, "info");
      onClose();
    };
    const failed = (err: unknown) => setError(apiErrorMessage(err, "Nie udało się zapisać umowy."));
    if (agreement) {
      update.mutate({ id: agreement.id, input }, { onSuccess: done, onError: failed });
    } else {
      create.mutate(input, { onSuccess: done, onError: failed });
    }
  };

  return (
    <AppModal
      open
      size="lg"
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={agreement ? `Szkic: ${agreement.title}` : `Nowa umowa albo aneks · ${overview.person.name}`}
      description="Treść daje wzór od Kadr; NEXUS wstawia pola. Do podpisu wysyłasz osobnym kliknięciem."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={pending || !templates.data}>
            {pending ? "Zapisywanie…" : agreement ? "Zapisz szkic" : "Utwórz szkic"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <FormField label="Wzór" htmlFor={id("template")} className="sm:col-span-2" required>
          <Select value={form.templateId || undefined} onValueChange={(value) => set("templateId", value)}>
            <SelectTrigger id={id("template")}>
              <SelectValue placeholder={templates.isLoading ? "Wczytywanie wzorów…" : "Wybierz wzór"} />
            </SelectTrigger>
            <SelectContent>
              {choices.map((item) => (
                <SelectItem key={item.templateId} value={String(item.templateId)}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {templates.isSuccess && choices.length === 0 ? (
          <p className="text-sm text-muted-foreground sm:col-span-2">
            Nie ma jeszcze wzorów umów — dodaje je Kadry w Ustawieniach → Kadry → „Wzory umów”.
          </p>
        ) : null}
        {templates.isError ? (
          <p role="alert" className="text-sm text-destructive sm:col-span-2">
            {apiErrorMessage(templates.error, "Nie udało się wczytać wzorów umów.")}
          </p>
        ) : null}
        {kind === "annex" ? (
          <FormField label="Zmienia umowę" htmlFor={id("base")} className="sm:col-span-2">
            <Select
              value={form.baseAgreementId || NONE}
              onValueChange={(value) => set("baseAgreementId", value === NONE ? "" : value)}
            >
              <SelectTrigger id={id("base")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>umowa spoza NEXUSA</SelectItem>
                {signedBases.map((row) => (
                  <SelectItem key={row.id} value={String(row.id)}>
                    {row.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        ) : null}
        <div className="grid grid-cols-[minmax(0,1fr)_6rem] gap-2">
          <FormField
            label={`Stawka ${employmentType === "b2b" ? "netto" : "brutto"} za godzinę`}
            htmlFor={id("rate")}
            description={
              minimum !== null ? `Minimum ${form.startDate.slice(0, 4)}: ${formatAmount(minimum)} zł` : undefined
            }
            required
          >
            <Input
              id={id("rate")}
              inputMode="decimal"
              placeholder="np. 32,00"
              value={form.rate}
              onChange={(event) => set("rate", event.target.value)}
            />
          </FormField>
          <FormField label="Waluta" htmlFor={id("currency")}>
            <Select value={form.currency} onValueChange={(value) => set("currency", value as Currency)}>
              <SelectTrigger id={id("currency")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((code) => (
                  <SelectItem key={code} value={code}>
                    {code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <FormField label="Data zawarcia" htmlFor={id("agreement-date")}>
          <Input
            id={id("agreement-date")}
            type="date"
            value={form.agreementDate}
            onChange={(event) => set("agreementDate", event.target.value)}
          />
        </FormField>
        <FormField
          label={kind === "annex" ? "Nowa stawka od" : "Od"}
          htmlFor={id("start")}
          description={kind === "annex" ? "1. dzień miesiąca" : undefined}
          required
        >
          <Input
            id={id("start")}
            type="date"
            value={form.startDate}
            onChange={(event) => set("startDate", event.target.value)}
          />
        </FormField>
        {kind === "agreement" ? (
          <div className="flex flex-col gap-1.5">
            <label className="flex items-center justify-between gap-3 text-sm" htmlFor={id("indefinite")}>
              <span>Bez daty końca</span>
              <Switch
                id={id("indefinite")}
                checked={form.indefinite}
                onCheckedChange={(checked) => set("indefinite", checked)}
                aria-label="Bez daty końca"
              />
            </label>
            {!form.indefinite ? (
              <Input
                id={id("end")}
                type="date"
                aria-label="Do"
                value={form.endDate}
                min={form.startDate || undefined}
                onChange={(event) => set("endDate", event.target.value)}
              />
            ) : null}
          </div>
        ) : null}
        {kind === "agreement" ? (
          <label className="flex items-center justify-between gap-3 text-sm sm:col-span-2">
            <span>
              {words.timesheet} co miesiąc w NEXUSIE
              <span className="block text-xs text-muted-foreground">
                {employmentType === "zlecenie"
                  ? "Na zleceniu obowiązkowe (art. 8b) — potwierdza koordynator."
                  : `Raport potwierdza ${words.coordinator}.`}
              </span>
            </span>
            <Switch
              checked={form.hoursConfirmation}
              disabled={employmentType === "zlecenie"}
              onCheckedChange={(checked) => set("hoursConfirmation", checked)}
              aria-label="Potwierdzanie godzin"
            />
          </label>
        ) : null}
        {employmentType !== "b2b" ? (
          <FormField
            label="Dzień wypłaty"
            htmlFor={id("payout")}
            description="Dzień następnego miesiąca (domyślnie z Ustawień Płac)."
          >
            <Input
              id={id("payout")}
              type="number"
              min={1}
              max={31}
              value={form.payoutDay}
              onChange={(event) => set("payoutDay", event.target.value)}
            />
          </FormField>
        ) : null}
        <FormField label={words.coordinator === "przełożony" ? "Przełożony" : "Koordynator"} htmlFor={id("coordinator")}>
          <Select
            value={form.coordinatorId || NONE}
            onValueChange={(value) => set("coordinatorId", value === NONE ? "" : value)}
          >
            <SelectTrigger id={id("coordinator")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>bez wskazania</SelectItem>
              {coordinators.map((row) => (
                <SelectItem key={row.user_id} value={String(row.user_id)}>
                  {row.name}
                </SelectItem>
              ))}
              {form.coordinatorId &&
              !coordinators.some((row) => String(row.user_id) === form.coordinatorId) ? (
                <SelectItem value={form.coordinatorId}>
                  {overview.defaults.coordinator_name ?? agreement?.coordinator_name ?? "koordynator z kartoteki"}
                </SelectItem>
              ) : null}
            </SelectContent>
          </Select>
        </FormField>
      </div>
      <div className="mt-4 rounded-lg border border-border bg-muted/40 p-3 text-sm">
        <p className="font-medium text-foreground">Po podpisaniu NEXUS sam:</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
          {afterSigning(context, form.startDate).map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}
