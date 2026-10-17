"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { FileDropZone } from "@/components/ds/FileDropZone";
import { nipValid } from "@/components/hr/me/settlement-format";
import { CURRENCIES, parseAmount, ymSegment } from "@/components/hr/payroll/payroll-format";
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
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import type { Currency } from "@/lib/api/hr-payroll";
import {
  useAddManualInvoice,
  useAssignInvoicePeriod,
  useIgnoreInvoice,
  useKsefRefetch,
  type KsefInvoice,
} from "@/lib/api/hr-ksef";
import { warsawToday } from "@/lib/warsaw-date";

import { MAX_INVOICE_PDF_BYTES, runSummary } from "./ksef-format";

export interface KsefPerson {
  user_id: number;
  name: string;
}

const ALL_PEOPLE = "all";

function parseMonth(value: string): { year: number; month: number } | null {
  const match = /^(\d{4})-(\d{2})$/.exec(value);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]) };
}

function PersonSelect({
  id,
  people,
  value,
  onChange,
  allLabel,
}: {
  id: string;
  people: KsefPerson[];
  value: string;
  onChange: (value: string) => void;
  allLabel?: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger id={id}>
        <SelectValue placeholder="Wybierz osobę" />
      </SelectTrigger>
      <SelectContent>
        {allLabel ? <SelectItem value={ALL_PEOPLE}>{allLabel}</SelectItem> : null}
        {people.map((person) => (
          <SelectItem key={person.user_id} value={String(person.user_id)}>
            {person.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function ErrorLine({ error }: { error: string | null }) {
  return error ? (
    <p role="alert" className="mt-4 text-sm text-destructive">
      {error}
    </p>
  ) : null;
}

/** „Pobierz ponownie okres”: od 1. dnia miesiąca do dziś, np. po dopisaniu NIP-u osobie. */
export function RefetchDialog({
  year,
  month,
  people,
  onClose,
}: {
  year: number;
  month: number;
  people: KsefPerson[];
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const refetch = useKsefRefetch();
  const [period, setPeriod] = useState(ymSegment(year, month));
  const [personId, setPersonId] = useState(ALL_PEOPLE);
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const parsed = parseMonth(period);
    if (!parsed) {
      setError("Wybierz miesiąc.");
      return;
    }
    refetch.mutate(
      {
        ...parsed,
        user_id: personId === ALL_PEOPLE ? undefined : Number(personId),
      },
      {
        onSuccess: (result) => {
          showToast(runSummary(result), "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się pobrać faktur z KSeF.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title="Pobierz ponownie okres"
      description="Pobiera z KSeF faktury od 1. dnia miesiąca do dziś, np. gdy osobie dopisano NIP. Pobieranie co godzinę idzie dalej bez zmian."
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={refetch.isPending}>
            {refetch.isPending ? "Pobieranie…" : "Pobierz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Od miesiąca" htmlFor="ksef-refetch-month">
          <Input
            id="ksef-refetch-month"
            type="month"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
          />
        </FormField>
        <FormField label="Czyje faktury" htmlFor="ksef-refetch-person">
          <PersonSelect
            id="ksef-refetch-person"
            people={people}
            value={personId}
            onChange={setPersonId}
            allLabel="Wszystkich z NIP-em w danych"
          />
        </FormField>
      </div>
      <ErrorLine error={error} />
    </AppModal>
  );
}

/** „Przypisz do miesiąca” (i do osoby, gdy NIP z faktury ma kilka osób). */
export function AssignPeriodDialog({
  invoice,
  year,
  month,
  people,
  onClose,
}: {
  invoice: KsefInvoice;
  year: number;
  month: number;
  people: KsefPerson[];
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const assign = useAssignInvoicePeriod();
  const [period, setPeriod] = useState(invoice.period ?? ymSegment(year, month));
  const [personId, setPersonId] = useState(invoice.user ? String(invoice.user.id) : "");
  const [error, setError] = useState<string | null>(null);
  const needsPerson = !invoice.user;

  const submit = () => {
    const parsed = parseMonth(period);
    if (!parsed) {
      setError("Wybierz miesiąc.");
      return;
    }
    if (needsPerson && !personId) {
      setError("Wybierz osobę, której jest ta faktura.");
      return;
    }
    assign.mutate(
      {
        invoiceId: invoice.id,
        ...parsed,
        userId: needsPerson ? Number(personId) : undefined,
      },
      {
        onSuccess: (row) => {
          showToast(
            row.match_status === "matched"
              ? "Faktura dopasowana do rozliczenia"
              : "Miesiąc zapisany — faktura czeka na rozliczenie tego miesiąca",
            "success",
          );
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
      title="Przypisz do miesiąca"
      description={`Faktura ${invoice.invoice_number}. NEXUS dopasuje ją do rozliczenia osoby za wybrany miesiąc.`}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={assign.isPending}>
            {assign.isPending ? "Zapisywanie…" : "Przypisz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Miesiąc rozliczenia" htmlFor="ksef-assign-month">
          <Input
            id="ksef-assign-month"
            type="month"
            value={period}
            onChange={(event) => setPeriod(event.target.value)}
          />
        </FormField>
        {needsPerson ? (
          <FormField
            label="Osoba"
            htmlFor="ksef-assign-person"
            description="Ten NIP ma w danych do rozliczeń więcej niż jedna osoba."
          >
            <PersonSelect
              id="ksef-assign-person"
              people={people}
              value={personId}
              onChange={setPersonId}
            />
          </FormField>
        ) : null}
      </div>
      <ErrorLine error={error} />
    </AppModal>
  );
}

/** „Pomiń” — faktura, która nie jest rozliczeniem miesiąca (powód w śladzie). */
export function IgnoreInvoiceDialog({
  invoice,
  onClose,
}: {
  invoice: KsefInvoice;
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const ignore = useIgnoreInvoice();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    if (!reason.trim()) {
      setError("Napisz, dlaczego faktura nie jest rozliczeniem.");
      return;
    }
    ignore.mutate(
      { invoiceId: invoice.id, ignored: true, reason: reason.trim() },
      {
        onSuccess: () => {
          showToast("Faktura pominięta", "success");
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się pominąć faktury.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title="Pomiń fakturę"
      description={`Faktura ${invoice.invoice_number} zniknie z listy do przypisania. Można ją przywrócić.`}
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={ignore.isPending}>
            {ignore.isPending ? "Zapisywanie…" : "Pomiń"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor="ksef-ignore-reason">
        <Textarea
          id="ksef-ignore-reason"
          value={reason}
          maxLength={500}
          rows={3}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Np. faktura za zwrot kosztów sprzętu, nie za usługi."
        />
      </FormField>
      <ErrorLine error={error} />
    </AppModal>
  );
}

interface ManualForm {
  personId: string;
  sellerNip: string;
  invoiceNumber: string;
  issueDate: string;
  saleDate: string;
  period: string;
  currency: Currency;
  net: string;
  vat: string;
  gross: string;
}

/** Sprawdzenie formularza przed wysyłką; serwer i tak sprawdza wszystko jeszcze raz. */
export function manualFormError(form: ManualForm, file: File | null): string | null {
  if (!form.personId) return "Wybierz osobę.";
  if (form.sellerNip.trim() && !nipValid(form.sellerNip)) {
    return "NIP sprzedawcy ma złą sumę kontrolną.";
  }
  if (!form.invoiceNumber.trim()) return "Wpisz numer faktury.";
  if (!form.issueDate) return "Wpisz datę wystawienia.";
  if (!parseMonth(form.period)) return "Wybierz miesiąc rozliczenia.";
  const net = parseAmount(form.net);
  const vat = parseAmount(form.vat || "0");
  const gross = parseAmount(form.gross);
  if (net === null || vat === null || gross === null) {
    return "Kwoty wpisz jak 1234,50 (najwyżej dwa miejsca po przecinku).";
  }
  if (Math.round((Number(net) + Number(vat)) * 100) !== Math.round(Number(gross) * 100)) {
    return "Netto + VAT musi dać brutto co do grosza.";
  }
  if (!file) return "Dołącz PDF faktury.";
  return null;
}

/** Faktura spoza KSeF (do końca 2026 r. sprzedaż do 10 000 zł brutto miesięcznie). */
export function ManualInvoiceDialog({
  year,
  month,
  people,
  onClose,
}: {
  year: number;
  month: number;
  people: KsefPerson[];
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const add = useAddManualInvoice();
  const [form, setForm] = useState<ManualForm>({
    personId: "",
    sellerNip: "",
    invoiceNumber: "",
    issueDate: warsawToday(),
    saleDate: "",
    period: ymSegment(year, month),
    currency: "PLN",
    net: "",
    vat: "0",
    gross: "",
  });
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof ManualForm) => (value: string) =>
    setForm((current) => ({ ...current, [key]: value }));

  const submit = () => {
    const problem = manualFormError(form, file);
    if (problem || !file) {
      setError(problem);
      return;
    }
    const period = parseMonth(form.period)!;
    add.mutate(
      {
        user_id: Number(form.personId),
        seller_nip: form.sellerNip.trim() || undefined,
        invoice_number: form.invoiceNumber.trim(),
        issue_date: form.issueDate,
        sale_date: form.saleDate || undefined,
        period_year: period.year,
        period_month: period.month,
        currency: form.currency,
        net_amount: parseAmount(form.net)!,
        vat_amount: parseAmount(form.vat || "0")!,
        gross_amount: parseAmount(form.gross)!,
        file,
      },
      {
        onSuccess: (row) => {
          showToast(
            row.match_status === "matched"
              ? "Faktura dodana i dopasowana do rozliczenia"
              : "Faktura dodana — czeka na rozliczenie miesiąca",
            "success",
          );
          onClose();
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się dodać faktury.")),
      },
    );
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title="Faktura spoza KSeF"
      description="Do końca 2026 r. poza KSeF może zostać sprzedaż do 10 000 zł brutto miesięcznie. Kwoty przepisz z PDF-u — NEXUS porówna netto z rozliczeniem."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={add.isPending}>
            {add.isPending ? "Zapisywanie…" : "Dodaj fakturę"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Osoba" htmlFor="ksef-manual-person">
          <PersonSelect
            id="ksef-manual-person"
            people={people}
            value={form.personId}
            onChange={set("personId")}
          />
        </FormField>
        <FormField
          label="NIP sprzedawcy"
          htmlFor="ksef-manual-nip"
          description="Gdy osoba nie ma jeszcze NIP-u w danych do rozliczeń."
        >
          <Input
            id="ksef-manual-nip"
            inputMode="numeric"
            value={form.sellerNip}
            onChange={(event) => set("sellerNip")(event.target.value)}
          />
        </FormField>
        <FormField label="Numer faktury" htmlFor="ksef-manual-number">
          <Input
            id="ksef-manual-number"
            value={form.invoiceNumber}
            maxLength={256}
            onChange={(event) => set("invoiceNumber")(event.target.value)}
          />
        </FormField>
        <FormField label="Miesiąc rozliczenia" htmlFor="ksef-manual-period">
          <Input
            id="ksef-manual-period"
            type="month"
            value={form.period}
            onChange={(event) => set("period")(event.target.value)}
          />
        </FormField>
        <FormField label="Data wystawienia" htmlFor="ksef-manual-issue">
          <Input
            id="ksef-manual-issue"
            type="date"
            value={form.issueDate}
            onChange={(event) => set("issueDate")(event.target.value)}
          />
        </FormField>
        <FormField label="Data sprzedaży (opcjonalnie)" htmlFor="ksef-manual-sale">
          <Input
            id="ksef-manual-sale"
            type="date"
            value={form.saleDate}
            onChange={(event) => set("saleDate")(event.target.value)}
          />
        </FormField>
        <div className="grid grid-cols-4 gap-3 sm:col-span-2">
          <FormField label="Netto" htmlFor="ksef-manual-net">
            <Input
              id="ksef-manual-net"
              inputMode="decimal"
              value={form.net}
              onChange={(event) => set("net")(event.target.value)}
            />
          </FormField>
          <FormField label="VAT" htmlFor="ksef-manual-vat">
            <Input
              id="ksef-manual-vat"
              inputMode="decimal"
              value={form.vat}
              onChange={(event) => set("vat")(event.target.value)}
            />
          </FormField>
          <FormField label="Brutto" htmlFor="ksef-manual-gross">
            <Input
              id="ksef-manual-gross"
              inputMode="decimal"
              value={form.gross}
              onChange={(event) => set("gross")(event.target.value)}
            />
          </FormField>
          <FormField label="Waluta" htmlFor="ksef-manual-currency">
            <Select value={form.currency} onValueChange={set("currency")}>
              <SelectTrigger id="ksef-manual-currency">
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
        <div className="sm:col-span-2">
          <FileDropZone
            inputId="ksef-manual-pdf"
            file={file}
            onPick={(picked) => {
              setFile(picked);
              setError(null);
            }}
            accept=".pdf"
            maxBytes={MAX_INVOICE_PDF_BYTES}
            label="PDF faktury"
            hint="Plik PDF do 10 MB"
            onError={setError}
          />
        </div>
      </div>
      <ErrorLine error={error} />
    </AppModal>
  );
}
