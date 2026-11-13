"use client";

import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";

import { ClientSinglePicker, type ClientRef } from "@/components/clients/ClientSinglePicker";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useIssueSettings,
  useSaveIssueSettings,
  useSetSeriesNext,
  type IssueCurrency,
  type IssueSettings,
  type SeriesCode,
  type SeriesState,
} from "@/lib/api/issued-invoices";
import { monthTitlePl } from "@/lib/date-pl";

import { splitPeriod } from "../invoicing-format";

const CURRENCIES: IssueCurrency[] = ["PLN", "EUR", "USD"];
const SELECT =
  "h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground";

/**
 * Ustawienia wystawiania (E4): dane sprzedawcy, rachunki per waluta, termin,
 * stawka VAT domyślna i przy kliencie, wzory serii i „następny numer” w miesiącu.
 * Zapis w `app_settings`, nie w kodzie — bez kompletu danych sprzedawcy
 * wysyłka do KSeF czeka.
 */
export function IssueSettingsPanel({ period }: { period: string }) {
  const { showToast } = useToast();
  const query = useIssueSettings(period);
  const save = useSaveIssueSettings();
  const [draft, setDraft] = useState<IssueSettings | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [newClient, setNewClient] = useState<ClientRef | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (query.data) {
      setDraft(query.data.settings);
      setNames(query.data.client_names);
    }
  }, [query.data]);

  if (query.isLoading) return <p className="py-6 text-sm text-muted-foreground">Wczytywanie ustawień…</p>;
  if (query.isError || !query.data || !draft) {
    return <QueryStateNotice state="error" onRetry={() => query.refetch()} />;
  }
  const data = query.data;

  const set = <K extends keyof IssueSettings>(key: K, value: IssueSettings[K]) =>
    setDraft((current) => (current ? { ...current, [key]: value } : current));
  const setSeller = (key: keyof IssueSettings["seller"], value: string) =>
    set("seller", { ...draft.seller, [key]: value });
  const setAccount = (currency: IssueCurrency, key: "number" | "bank" | "swift", value: string) =>
    set("accounts", { ...draft.accounts, [currency]: { ...draft.accounts[currency], [key]: value } });

  const addClient = () => {
    if (!newClient) return;
    set("clients", { ...draft.clients, [String(newClient.id)]: { vat_rate: draft.default_vat } });
    setNames((current) => ({ ...current, [String(newClient.id)]: newClient.name }));
    setNewClient(null);
  };

  const submit = () => {
    setError(null);
    save.mutate(draft, {
      onSuccess: () => showToast("Zapisano ustawienia wystawiania", "success"),
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać ustawień.")),
    });
  };

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-border bg-card px-4 py-3">
        <StatusDot tone={data.ksef.enabled ? "success" : "neutral"}>
          Wysyłka do KSeF: {data.ksef.mode_label}
        </StatusDot>
        {data.ksef.disabled_reason ? (
          <p className="mt-1 text-xs text-muted-foreground">{data.ksef.disabled_reason}</p>
        ) : null}
        {data.missing.length ? (
          <p className="mt-1 text-xs text-destructive">
            Do wysyłki brakuje: {data.missing.join(", ")}.
          </p>
        ) : null}
      </section>

      <section aria-labelledby="issue-seller" className="rounded-lg border border-border bg-card px-4 py-3">
        <h3 id="issue-seller" className="mb-2 text-sm font-semibold text-foreground">
          Sprzedawca
        </h3>
        <div className="grid gap-3 md:grid-cols-2">
          <FormField label="Nazwa" htmlFor="seller-name">
            <Input id="seller-name" value={draft.seller.name} onChange={(e) => setSeller("name", e.target.value)} />
          </FormField>
          <FormField label="NIP" htmlFor="seller-nip" description="Ten sam co NIP spółki w KSeF.">
            <Input
              id="seller-nip"
              inputMode="numeric"
              value={draft.seller.nip}
              onChange={(e) => setSeller("nip", e.target.value)}
            />
          </FormField>
          <FormField label="Adres (ulica, kod, miasto)" htmlFor="seller-address">
            <Input
              id="seller-address"
              value={draft.seller.address_l1}
              onChange={(e) => setSeller("address_l1", e.target.value)}
            />
          </FormField>
          <FormField label="Miejsce wystawienia" htmlFor="seller-place">
            <Input
              id="seller-place"
              value={draft.seller.issue_place}
              onChange={(e) => setSeller("issue_place", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section aria-labelledby="issue-accounts" className="rounded-lg border border-border bg-card px-4 py-3">
        <h3 id="issue-accounts" className="mb-2 text-sm font-semibold text-foreground">
          Rachunki i płatność
        </h3>
        <div className="space-y-2">
          {CURRENCIES.map((currency) => (
            <div key={currency} className="grid gap-2 md:grid-cols-[4rem_minmax(0,2fr)_minmax(0,1fr)_8rem]">
              <span className="self-center text-sm font-medium text-foreground">{currency}</span>
              <Input
                aria-label={`Rachunek ${currency}`}
                placeholder="Numer rachunku (IBAN)"
                value={draft.accounts[currency].number}
                onChange={(e) => setAccount(currency, "number", e.target.value)}
              />
              <Input
                aria-label={`Bank ${currency}`}
                placeholder="Bank"
                value={draft.accounts[currency].bank}
                onChange={(e) => setAccount(currency, "bank", e.target.value)}
              />
              <Input
                aria-label={`SWIFT ${currency}`}
                placeholder="SWIFT"
                value={draft.accounts[currency].swift}
                onChange={(e) => setAccount(currency, "swift", e.target.value)}
              />
            </div>
          ))}
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <FormField label="Termin płatności (dni)" htmlFor="issue-days">
            <Input
              id="issue-days"
              type="number"
              min={0}
              max={180}
              value={draft.payment_days}
              onChange={(e) => set("payment_days", Number(e.target.value))}
            />
          </FormField>
          <FormField label="Stawka VAT domyślna" htmlFor="issue-vat" description="Nabywca z UE dostaje „np.” sam.">
            <select
              id="issue-vat"
              className={SELECT}
              value={draft.default_vat}
              onChange={(e) => set("default_vat", e.target.value)}
            >
              {data.vat_rates.map((rate) => (
                <option key={rate.code} value={rate.code}>
                  {rate.label}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Nazwa usługi w pozycji" htmlFor="issue-service">
            <Input
              id="issue-service"
              value={draft.service_name}
              onChange={(e) => set("service_name", e.target.value)}
            />
          </FormField>
        </div>
        <FormField
          label="Podstawa zwolnienia z VAT"
          htmlFor="issue-exemption"
          description="Potrzebna tylko przy pozycjach „zw.” (np. przepis ustawy o VAT)."
          className="mt-3"
        >
          <Input
            id="issue-exemption"
            value={draft.exemption_basis}
            onChange={(e) => set("exemption_basis", e.target.value)}
          />
        </FormField>
      </section>

      <section aria-labelledby="issue-clients" className="rounded-lg border border-border bg-card px-4 py-3">
        <h3 id="issue-clients" className="mb-2 text-sm font-semibold text-foreground">
          Stawka i termin przy kliencie
        </h3>
        {Object.keys(draft.clients).length === 0 ? (
          <p className="text-sm text-muted-foreground">Wszyscy klienci mają ustawienia domyślne.</p>
        ) : (
          <ul className="divide-y divide-border/60">
            {Object.entries(draft.clients).map(([id, entry]) => (
              <li key={id} className="grid items-center gap-2 py-2 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_8rem_2.5rem]">
                <span className="truncate text-sm text-foreground">{names[id] ?? `Klient #${id}`}</span>
                <select
                  aria-label={`Stawka VAT — ${names[id] ?? id}`}
                  className={SELECT}
                  value={entry.vat_rate ?? draft.default_vat}
                  onChange={(e) =>
                    set("clients", { ...draft.clients, [id]: { ...entry, vat_rate: e.target.value } })
                  }
                >
                  {data.vat_rates.map((rate) => (
                    <option key={rate.code} value={rate.code}>
                      {rate.label}
                    </option>
                  ))}
                </select>
                <Input
                  aria-label={`Termin (dni) — ${names[id] ?? id}`}
                  type="number"
                  min={0}
                  max={180}
                  placeholder={String(draft.payment_days)}
                  value={entry.payment_days ?? ""}
                  onChange={(e) =>
                    set("clients", {
                      ...draft.clients,
                      [id]: {
                        ...entry,
                        payment_days: e.target.value === "" ? undefined : Number(e.target.value),
                      },
                    })
                  }
                />
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label={`Usuń ustawienie klienta ${names[id] ?? id}`}
                  onClick={() => {
                    const rest = { ...draft.clients };
                    delete rest[id];
                    set("clients", rest);
                  }}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
          <ClientSinglePicker value={newClient} onChange={setNewClient} queryKey="issued-settings-clients" />
          <Button size="sm" variant="outline" onClick={addClient} disabled={!newClient}>
            Dodaj klienta
          </Button>
        </div>
      </section>

      <SeriesSection
        series={data.series}
        labels={data.series_labels}
        patterns={draft.series}
        period={data.series_period}
        onPattern={(code, value) => set("series", { ...draft.series, [code]: value })}
      />

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button onClick={submit} disabled={save.isPending}>
          {save.isPending ? "Zapisywanie…" : "Zapisz ustawienia"}
        </Button>
      </div>
    </div>
  );
}

function SeriesSection({
  series,
  labels,
  patterns,
  period,
  onPattern,
}: {
  series: SeriesState[];
  labels: Record<SeriesCode, string>;
  patterns: Record<SeriesCode, string>;
  period: string;
  onPattern: (code: SeriesCode, value: string) => void;
}) {
  const { showToast } = useToast();
  const setNext = useSetSeriesNext();
  const { year, month } = splitPeriod(period);
  const [next, setNextValues] = useState<Record<string, string>>({});

  const apply = (code: SeriesCode) => {
    const value = Number(next[code]);
    if (!Number.isInteger(value) || value < 1) {
      showToast("Następny numer to liczba od 1.", "error");
      return;
    }
    setNext.mutate(
      { code, year, month, next_number: value },
      {
        onSuccess: () => showToast(`Seria „${labels[code]}”: następny numer ${value}`, "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się ustawić numeru."), "error"),
      },
    );
  };

  return (
    <section aria-labelledby="issue-series" className="rounded-lg border border-border bg-card px-4 py-3">
      <h3 id="issue-series" className="text-sm font-semibold text-foreground">
        Serie numeracji
      </h3>
      <p className="mb-2 text-xs text-muted-foreground">
        Wzór: {"{n}"} numer, {"{mm}"} miesiąc, {"{yyyy}"} rok. „Następny numer” dotyczy{" "}
        {monthTitlePl(period).toLowerCase()} — przy przejściu z eBI24 wpisz numer po ostatnim
        wystawionym tam.
      </p>
      <ul className="divide-y divide-border/60">
        {series.map((row) => (
          <li
            key={row.code}
            className="grid items-center gap-2 py-2 md:grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)_7rem_auto]"
          >
            <span className="text-sm font-medium text-foreground">{labels[row.code]}</span>
            <Input
              aria-label={`Wzór serii ${labels[row.code]}`}
              value={patterns[row.code]}
              onChange={(e) => onPattern(row.code, e.target.value)}
            />
            <span className="text-sm text-muted-foreground">
              następna: <span className="text-foreground">{row.next_label}</span>
              {row.highest_issued ? ` · ostatni wydany ${row.highest_issued}` : ""}
            </span>
            <Input
              aria-label={`Następny numer — ${labels[row.code]}`}
              type="number"
              min={1}
              placeholder={String(row.next_number)}
              value={next[row.code] ?? ""}
              onChange={(e) => setNextValues((current) => ({ ...current, [row.code]: e.target.value }))}
            />
            <Button size="sm" variant="outline" onClick={() => apply(row.code)} disabled={!next[row.code]}>
              Ustaw
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
