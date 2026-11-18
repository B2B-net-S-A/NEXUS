"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useSetBankSettings, type BankCurrency, type BankSettings } from "@/lib/api/accounting-bank";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_HEAD, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import {
  BANK_CURRENCIES,
  companyAccountProblems,
  groupNrb,
  nrbDigits,
  type CompanyAccountDraft,
} from "./bank-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const ACCOUNTS_MAX = 20;

type RuleKey =
  | "fees_account"
  | "zus_account"
  | "vat_account"
  | "pit_account"
  | "cit_account"
  | "fx_loss_account"
  | "fx_gain_account";

const RULE_FIELDS: { key: RuleKey; label: string; hint: string; placeholder: string }[] = [
  { key: "zus_account", label: "ZUS", hint: "przelew na rachunek ZUS (numer banku 60000002)", placeholder: "np. 229" },
  { key: "pit_account", label: "PIT-4 i PIT", hint: "mikrorachunek podatkowy, w tytule /SFP/PIT", placeholder: "np. 225" },
  { key: "vat_account", label: "VAT", hint: "mikrorachunek podatkowy, w tytule /SFP/VAT", placeholder: "np. 222" },
  { key: "cit_account", label: "CIT", hint: "mikrorachunek podatkowy, w tytule /SFP/CIT", placeholder: "np. 220" },
  { key: "fees_account", label: "Opłaty i prowizje banku", hint: "operacja bez rachunku kontrahenta, „opłata/prowizja” w tytule", placeholder: "np. 409" },
  { key: "fx_loss_account", label: "Ujemne różnice kursowe", hint: "koszty finansowe — rozliczenie w walucie: wpłata dała mniej PLN niż faktura", placeholder: "np. 751" },
  { key: "fx_gain_account", label: "Dodatnie różnice kursowe", hint: "przychody finansowe — wpłata dała więcej PLN niż faktura", placeholder: "np. 750" },
];

const EMPTY: BankSettings = {
  accounts: [],
  fees_account: "",
  zus_account: "",
  vat_account: "",
  pit_account: "",
  cit_account: "",
  fx_gain_account: "",
  fx_loss_account: "",
};

let rowSeq = 0;
function draftRows(settings: BankSettings): CompanyAccountDraft[] {
  return settings.accounts.map((item) => {
    rowSeq += 1;
    return {
      key: `r${rowSeq}`,
      number: groupNrb(item.number),
      account: item.account,
      name: item.name,
      currency: item.currency ?? "PLN",
    };
  });
}

function emptyRow(): CompanyAccountDraft {
  rowSeq += 1;
  return { key: `r${rowSeq}`, number: "", account: "", name: "", currency: "PLN" };
}

/** Ustawienia → rachunki firmy (NRB → konto 130-x) i konta reguł wyciągu (K4a). Zmienia administrator. */
export function BankSettingsCard() {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const save = useSetBankSettings();
  const saved = config.bank_settings ?? EMPTY;
  const admin = config.me.admin;
  const [rows, setRows] = useState<CompanyAccountDraft[]>(() => draftRows(saved));
  const [rules, setRules] = useState<Record<RuleKey, string>>(() => pickRules(saved));
  useEffect(() => {
    setRows(draftRows(saved));
    setRules(pickRules(saved));
  }, [saved]);

  const problems = companyAccountProblems(rows);
  const dirty = useMemo(() => {
    const sameRows =
      rows.length === saved.accounts.length &&
      rows.every((row, index) => {
        const item = saved.accounts[index];
        return (
          nrbDigits(row.number) === item.number &&
          row.account.trim() === item.account &&
          row.name.trim() === item.name &&
          row.currency === (item.currency ?? "PLN")
        );
      });
    const sameRules = RULE_FIELDS.every((field) => rules[field.key].trim() === (saved[field.key] ?? ""));
    return !sameRows || !sameRules;
  }, [rows, rules, saved]);

  const update = (key: string, patch: Partial<CompanyAccountDraft>) =>
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));

  const submit = () =>
    save.mutate(
      {
        accounts: rows.map((row) => ({
          number: nrbDigits(row.number),
          account: row.account.trim(),
          name: row.name.trim(),
          currency: row.currency,
        })),
        ...(Object.fromEntries(RULE_FIELDS.map((field) => [field.key, rules[field.key].trim()])) as Record<RuleKey, string>),
      },
      {
        onSuccess: () => showToast("Zapisano rachunki firmy i konta wyciągów."),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać rachunków."), "error"),
      },
    );

  return (
    <SectionCard title="Rachunki firmy i konta wyciągów" aside={admin ? "wyciąg wgrywa się w zakładce Bank" : "zmienia administrator"}>
      <div className="space-y-3 px-3.5 py-3 text-[13px]">
        <div>
          <p className={CALM_HEAD}>Rachunki firmy</p>
          <p className={CALM_SUBLINE}>
            Wyciąg z rachunku spoza listy jest odrzucany, a plik musi być w walucie rachunku. Konto rachunku musi być w
            Planie kont.
          </p>
          {rows.length ? (
            <div className="mt-2 space-y-2">
              {rows.map((row, index) => (
                <div key={row.key} className="space-y-1.5 rounded-md border border-border/70 p-2">
                  <div className="flex items-center gap-1.5">
                    <input
                      aria-label={`Numer rachunku ${index + 1}`}
                      className={cn(CONTROL, "w-0 min-w-0 flex-1 tabular-nums")}
                      value={row.number}
                      disabled={!admin}
                      placeholder="26 cyfr, z PL albo bez"
                      onChange={(event) => update(row.key, { number: event.target.value })}
                    />
                    {admin ? (
                      <button
                        type="button"
                        aria-label={`Usuń rachunek ${index + 1}`}
                        onClick={() => setRows((current) => current.filter((item) => item.key !== row.key))}
                        className="grid h-7 w-7 shrink-0 place-items-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    ) : null}
                  </div>
                  <div className="grid grid-cols-[110px_74px_minmax(0,1fr)] gap-1.5">
                    <input
                      aria-label={`Konto rachunku ${index + 1}`}
                      className={cn(CONTROL, "min-w-0 tabular-nums")}
                      value={row.account}
                      disabled={!admin}
                      placeholder="konto, np. 130-1"
                      onChange={(event) => update(row.key, { account: event.target.value })}
                    />
                    <select
                      aria-label={`Waluta rachunku ${index + 1}`}
                      className={cn(CONTROL, "min-w-0 px-1.5")}
                      value={row.currency}
                      disabled={!admin}
                      onChange={(event) => update(row.key, { currency: event.target.value as BankCurrency })}
                    >
                      {BANK_CURRENCIES.map((currency) => (
                        <option key={currency} value={currency}>
                          {currency}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label={`Nazwa rachunku ${index + 1}`}
                      className={cn(CONTROL, "min-w-0")}
                      value={row.name}
                      maxLength={80}
                      disabled={!admin}
                      placeholder="nazwa, np. rachunek bieżący"
                      onChange={(event) => update(row.key, { name: event.target.value })}
                    />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-2 text-muted-foreground">Nie ma jeszcze rachunków — bez nich zakładka Bank nie przyjmie wyciągu.</p>
          )}
          {admin && rows.length < ACCOUNTS_MAX ? (
            <Button size="sm" variant="ghost" className="mt-1.5 h-7 px-2" onClick={() => setRows((current) => [...current, emptyRow()])}>
              <Plus className="h-3.5 w-3.5" />
              Dodaj rachunek
            </Button>
          ) : null}
        </div>
        <div>
          <p className={CALM_HEAD}>Konta reguł</p>
          <p className={CALM_SUBLINE}>Puste konto = operacja czeka na ręczne przypisanie w zakładce Bank.</p>
          <div className="mt-2 space-y-2">
            {RULE_FIELDS.map((field) => (
              <label key={field.key} className="grid grid-cols-[minmax(0,1fr)_120px] items-center gap-x-3 gap-y-0.5">
                <span className="min-w-0">
                  <span className="block font-medium">{field.label}</span>
                  <span className={CALM_SUBLINE}>{field.hint}</span>
                </span>
                <input
                  aria-label={field.label}
                  className={cn(CONTROL, "w-full tabular-nums")}
                  value={rules[field.key]}
                  disabled={!admin}
                  placeholder={field.placeholder}
                  onChange={(event) => setRules((current) => ({ ...current, [field.key]: event.target.value }))}
                />
              </label>
            ))}
          </div>
        </div>
        {admin ? (
          <div className="flex items-start justify-between gap-3 pt-1">
            <span className="text-[12px] leading-5 text-muted-foreground">
              {problems.length ? <span className="text-warning-muted-foreground">{problems[0]}</span> : "Konto z Planu kont, bez kont analitycznych pod sobą."}
            </span>
            <Button size="sm" disabled={!dirty || problems.length > 0} loading={save.isPending} onClick={submit}>
              Zapisz
            </Button>
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}

function pickRules(settings: BankSettings): Record<RuleKey, string> {
  return {
    fees_account: settings.fees_account,
    zus_account: settings.zus_account,
    vat_account: settings.vat_account,
    pit_account: settings.pit_account,
    cit_account: settings.cit_account,
    fx_loss_account: settings.fx_loss_account ?? "",
    fx_gain_account: settings.fx_gain_account ?? "",
  };
}
