"use client";

import { useState } from "react";
import { ListChecks } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { accountLabel, formatNip, nipValid } from "@/components/hr/me/settlement-format";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBillingDetails,
  useSaveBilling,
  useSelectWhiteListAccount,
  useWhiteListLookup,
  type BillingDetails,
  type BillingInput,
  type WhiteListLookup,
} from "@/lib/api/hr-settlements";
import { formatIsoDatePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

const VAT_LABELS: Record<NonNullable<BillingDetails["vat_status"]>, string> = {
  active: "czynny",
  exempt: "zwolniony",
  unregistered: "niezarejestrowany",
};

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border/60 py-1.5 text-sm last:border-b-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium text-foreground">{children}</span>
    </div>
  );
}

/** Zmienione pola formularza — serwer dostaje tylko to, co się zmienia. */
export function billingChanges(
  data: Pick<BillingDetails, "nip" | "payment_terms_days" | "symfonia_id">,
  form: { nip: string; terms: string; symfonia: string; account: string },
): BillingInput {
  const changes: BillingInput = {};
  const nip = form.nip.replace(/[\s-]/g, "");
  if (nip !== (data.nip ?? "")) changes.nip = nip || null;
  if (form.terms.trim() !== String(data.payment_terms_days)) {
    changes.payment_terms_days = Number(form.terms);
  }
  const symfonia = form.symfonia.trim();
  if (symfonia !== (data.symfonia_id ?? "")) changes.symfonia_id = symfonia || null;
  if (form.account.trim()) changes.account = form.account.trim();
  return changes;
}

function WhiteListAccounts({
  lookup,
  onPick,
  busy,
}: {
  lookup: WhiteListLookup;
  onPick: (ref: number) => void;
  busy: boolean;
}) {
  if (!lookup.found) {
    return (
      <p className="text-sm text-muted-foreground">
        Tego NIP-u nie ma w wykazie podatników VAT. Rachunek można wpisać ręcznie — na B2B
        zapłata będzie wymagać drugiej osoby.
      </p>
    );
  }
  if (lookup.accounts.length === 0) {
    return <p className="text-sm text-muted-foreground">Wykaz nie podaje rachunków tej firmy.</p>;
  }
  return (
    <ul className="space-y-1" aria-label="Rachunki z białej listy VAT">
      {lookup.accounts.map((account) => (
        <li key={account.ref} className="flex items-center justify-between gap-3 text-sm">
          <span className="text-foreground">•• {account.last4} · na białej liście VAT</span>
          {account.selected ? (
            <span className="text-xs text-muted-foreground">wybrany</span>
          ) : (
            <Button size="sm" variant="outline" onClick={() => onPick(account.ref)} disabled={busy}>
              Wybierz
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}

function BillingForm({ data }: { data: BillingDetails }) {
  const { showToast } = useToast();
  const save = useSaveBilling(data.user_id);
  const lookup = useWhiteListLookup(data.user_id);
  const pick = useSelectWhiteListAccount(data.user_id);
  const [nip, setNip] = useState(data.nip ?? "");
  const [terms, setTerms] = useState(String(data.payment_terms_days));
  const [symfonia, setSymfonia] = useState(data.symfonia_id ?? "");
  const [account, setAccount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [found, setFound] = useState<WhiteListLookup | null>(null);
  const b2b = data.employment_type === "b2b";
  const nipHint = nip.trim() && !nipValid(nip) ? "NIP ma 10 cyfr i sumę kontrolną — sprawdź cyfry." : undefined;

  const submit = () => {
    setError(null);
    const changes = billingChanges(data, { nip, terms, symfonia, account });
    if (Object.keys(changes).length === 0) {
      showToast("Bez zmian", "success");
      return;
    }
    save.mutate(changes, {
      onSuccess: () => {
        setAccount("");
        showToast("Dane do rozliczeń zapisane", "success");
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać danych.")),
    });
  };

  const fetchWhiteList = () => {
    setError(null);
    lookup.mutate(undefined, {
      onSuccess: (result) => setFound(result),
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się sprawdzić białej listy.")),
    });
  };

  const pickAccount = (ref: number) => {
    setError(null);
    pick.mutate(ref, {
      onSuccess: () => {
        setFound(null);
        showToast("Rachunek z białej listy zapisany", "success");
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać rachunku.")),
    });
  };

  const clearAccount = () =>
    save.mutate(
      { clear_account: true },
      {
        onSuccess: () => showToast("Rachunek usunięty", "success"),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się usunąć rachunku.")),
      },
    );

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="space-y-2" aria-labelledby={`billing-company-${data.user_id}`}>
        <div className="flex items-center justify-between gap-2">
          <h3
            id={`billing-company-${data.user_id}`}
            className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
          >
            Firma
          </h3>
          <Button
            size="sm"
            variant="outline"
            onClick={fetchWhiteList}
            disabled={!data.nip || lookup.isPending}
            title={data.nip ? undefined : "Najpierw zapisz NIP."}
          >
            <ListChecks className="h-4 w-4" aria-hidden />
            {lookup.isPending ? "Sprawdzanie…" : "Pobierz z białej listy"}
          </Button>
        </div>
        <FormField label="NIP" htmlFor={`billing-nip-${data.user_id}`} description={nipHint}>
          <Input
            id={`billing-nip-${data.user_id}`}
            value={nip}
            inputMode="numeric"
            maxLength={20}
            onChange={(event) => setNip(event.target.value)}
          />
        </FormField>
        <Fact label="Nazwa z wykazu">{data.registry_name ?? "—"}</Fact>
        <Fact label="Status VAT">
          {data.vat_status
            ? `${VAT_LABELS[data.vat_status]} · sprawdzono ${formatIsoDatePl(data.vat_checked_at)}`
            : data.vat_checked_at
              ? `brak w wykazie · ${formatIsoDatePl(data.vat_checked_at)}`
              : "nie sprawdzano"}
        </Fact>
        <p className="text-xs text-muted-foreground">Z NIP-u NEXUS rozpoznaje faktury tej osoby w KSeF.</p>
        {found ? <WhiteListAccounts lookup={found} onPick={pickAccount} busy={pick.isPending} /> : null}
      </section>
      <section className="space-y-2" aria-labelledby={`billing-account-${data.user_id}`}>
        <h3
          id={`billing-account-${data.user_id}`}
          className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
        >
          Rachunek do przelewów
        </h3>
        <Fact label="Rachunek">{accountLabel(data.account_last4, data.account_source)}</Fact>
        {data.needs_second_person ? (
          <p className="text-xs text-muted-foreground">
            Na B2B rachunek spoza białej listy VAT — zapłata wymaga drugiej osoby z Płac.
          </p>
        ) : null}
        <FormField
          label={data.account_last4 ? "Zmień rachunek (wpis ręczny)" : "Rachunek (wpis ręczny)"}
          htmlFor={`billing-account-input-${data.user_id}`}
          description={
            b2b
              ? "Na B2B wybierz rachunek z białej listy; wpis ręczny tylko, gdy osoby nie ma w wykazie."
              : "Na zleceniu i UoP rachunek z umowy."
          }
        >
          <Input
            id={`billing-account-input-${data.user_id}`}
            value={account}
            autoComplete="off"
            maxLength={40}
            placeholder="PL i 26 cyfr"
            onChange={(event) => setAccount(event.target.value)}
          />
        </FormField>
        <div className="grid gap-2 sm:grid-cols-2">
          <FormField label="Termin płatności (dni)" htmlFor={`billing-terms-${data.user_id}`}>
            <Input
              id={`billing-terms-${data.user_id}`}
              type="number"
              min={0}
              max={90}
              value={terms}
              onChange={(event) => setTerms(event.target.value)}
            />
          </FormField>
          <FormField label="Identyfikator w Symfonii" htmlFor={`billing-symfonia-${data.user_id}`}>
            <Input
              id={`billing-symfonia-${data.user_id}`}
              value={symfonia}
              maxLength={64}
              onChange={(event) => setSymfonia(event.target.value)}
            />
          </FormField>
        </div>
        <p className="text-xs text-muted-foreground">
          {b2b ? "Termin liczy się od numeru KSeF faktury. " : ""}
          PESEL zostaje w programie kadrowo-płacowym — tu tylko GUID albo numer ewidencyjny z Symfonii.
        </p>
      </section>
      <div className="flex flex-wrap items-center justify-end gap-2 lg:col-span-2">
        {error ? (
          <p role="alert" className="mr-auto text-sm text-destructive">
            {error}
          </p>
        ) : null}
        {data.account_last4 ? (
          <Button variant="quiet" size="sm" onClick={clearAccount} disabled={save.isPending}>
            Usuń rachunek
          </Button>
        ) : null}
        <Button size="sm" onClick={submit} disabled={save.isPending}>
          {save.isPending ? "Zapisywanie…" : "Zapisz"}
        </Button>
      </div>
    </div>
  );
}

function BillingReadOnly({ data }: { data: BillingDetails }) {
  return (
    <div className="grid gap-x-6 lg:grid-cols-2">
      <div>
        <Fact label="NIP">{formatNip(data.nip)}</Fact>
        <Fact label="Nazwa z wykazu">{data.registry_name ?? "—"}</Fact>
        <Fact label="Status VAT">{data.vat_status ? VAT_LABELS[data.vat_status] : "—"}</Fact>
      </div>
      <div>
        <Fact label="Rachunek">{accountLabel(data.account_last4, data.account_source)}</Fact>
        <Fact label="Termin płatności">{data.payment_terms_days} dni</Fact>
      </div>
      <p className="mt-2 text-xs text-muted-foreground lg:col-span-2">
        Zmianę rachunku albo NIP-u zgłoś Kadrom — numer „mailem” nie przechodzi bez sprawdzenia.
      </p>
    </div>
  );
}

/**
 * Kartoteka → „Dane do rozliczeń” (M7, R6): NIP, wykaz VAT, rachunek (tylko
 * 4 cyfry), termin, identyfikator w Symfonii. Widzą osoba, Kadry i Płace —
 * przełożony i zespół nie (serwer odpowiada 404, sekcja się chowa).
 */
export function BillingDetailsSection({ userId, enabled }: { userId: number; enabled: boolean }) {
  const query = useBillingDetails(userId, enabled);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (!enabled || state === "forbidden" || state === "not_found") return null;
  return (
    <Card className="space-y-3 p-4" aria-labelledby={`billing-title-${userId}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2
          id={`billing-title-${userId}`}
          className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground"
        >
          Dane do rozliczeń
        </h2>
        <span className="text-xs text-muted-foreground">widzą tylko osoba, Kadry i Płace</span>
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : state !== "ready" || !query.data ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać danych do rozliczeń."
          onRetry={() => query.refetch()}
        />
      ) : query.data.can_edit ? (
        <BillingForm key={query.data.updated_at ?? "new"} data={query.data} />
      ) : (
        <BillingReadOnly data={query.data} />
      )}
    </Card>
  );
}
