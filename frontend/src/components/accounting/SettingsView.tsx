"use client";

import { useEffect, useState } from "react";

import { QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  useAccountantCandidates,
  useClosePeriod,
  useCreateYear,
  useReopenPeriod,
  useSetAccountants,
  useSetModule,
  useSetSalesAccounts,
  useSetYearMode,
  type LedgerPeriod,
  type LedgerYear,
  type SalesAccounts,
  type YearMode,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { MONTHS_PL } from "./ledger-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];

export function SettingsView() {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const setModule = useSetModule();

  return (
    <div className="grid gap-3.5 xl:grid-cols-2">
      <SectionCard title="Moduły" aside={config.me.admin ? "wyłączony = widzi tylko administrator" : "zmienia administrator"}>
        <table className="w-full table-fixed text-sm">
          <tbody>
            {config.modules.map((module) => (
              <tr key={module.key} className={cn(CALM_ROW, "align-top last:border-0")}>
                <td className="px-3.5 py-2">
                  <span className="font-medium">{module.label}</span>
                  <span className={CALM_SUBLINE}>zastępuje: {module.replaces}</span>
                </td>
                <td className="w-[104px] px-2 py-2 text-[12px] text-muted-foreground">
                  {module.built ? `etap ${module.stage}` : `w budowie, ${module.stage}`}
                </td>
                <td className="w-[64px] px-3.5 py-2 text-right">
                  <Switch
                    checked={module.enabled}
                    disabled={!config.me.admin || !module.built || setModule.isPending}
                    aria-label={`${module.enabled ? "Wyłącz" : "Włącz"}: ${module.label}`}
                    onCheckedChange={(enabled) =>
                      setModule.mutate(
                        { module: module.key, enabled },
                        {
                          onSuccess: () => showToast(enabled ? `Włączono: ${module.label}.` : `Wyłączono: ${module.label}.`),
                          onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zmienić modułu."), "error"),
                        },
                      )
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </SectionCard>

      <div className="space-y-3.5">
        <Accountants />
        <SalesAccountsCard />
      </div>

      <div className="xl:col-span-2">
        <Years />
      </div>
    </div>
  );
}

function Accountants() {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const candidates = useAccountantCandidates(config.me.admin);
  const save = useSetAccountants();
  const [chosen, setChosen] = useState<Set<number>>(new Set(config.accountants ?? []));
  useEffect(() => setChosen(new Set(config.accountants ?? [])), [config.accountants]);

  if (!config.me.admin) {
    return (
      <SectionCard title="Kto zatwierdza zapisy">
        <div className="space-y-2 px-3.5 py-3 text-[13px]">
          <StatusDot tone={config.me.approver ? "success" : "neutral"}>
            {config.me.approver ? "Jesteś na liście „Księgowi”" : "Nie jesteś na liście „Księgowi”"}
          </StatusDot>
          <p className="text-muted-foreground">
            Zatwierdzanie bufora, storno i zamknięcie okresu robi osoba z listy „Księgowi” albo administrator. Listę
            ustawia administrator.
          </p>
        </div>
      </SectionCard>
    );
  }
  const items = candidates.data ?? [];
  const dirty =
    chosen.size !== (config.accountants ?? []).length ||
    [...chosen].some((id) => !(config.accountants ?? []).includes(id));
  return (
    <SectionCard title="Lista „Księgowi”" aside="zatwierdzanie, storno, zamknięcie okresu">
      {candidates.isLoading ? (
        <p className="px-3.5 py-3 text-sm text-muted-foreground">Wczytywanie osób…</p>
      ) : candidates.isError ? (
        <QueryStateNotice state="error" onRetry={() => candidates.refetch()} className="m-3" />
      ) : (
        <>
          <ul className="max-h-[260px] divide-y divide-border/60 overflow-y-auto">
            {items.map((person) => (
              <li key={person.id}>
                <label className="flex cursor-pointer items-center gap-2.5 px-3.5 py-2 text-[13px] hover:bg-muted/40">
                  <input
                    type="checkbox"
                    checked={person.admin || chosen.has(person.id)}
                    disabled={person.admin}
                    onChange={(e) =>
                      setChosen((current) => {
                        const next = new Set(current);
                        if (e.target.checked) next.add(person.id);
                        else next.delete(person.id);
                        return next;
                      })
                    }
                  />
                  <span className="min-w-0 flex-1 truncate">{person.name ?? "—"}</span>
                  {person.admin ? <span className="text-[12px] text-muted-foreground">administrator — zawsze</span> : null}
                </label>
              </li>
            ))}
          </ul>
          <div className="flex items-center justify-between gap-3 border-t border-border/70 px-3.5 py-2.5">
            <span className="text-[12px] text-muted-foreground">Na liście tylko konta z „Modułem Finanse”.</span>
            <Button
              size="sm"
              disabled={!dirty}
              loading={save.isPending}
              onClick={() =>
                save.mutate([...chosen], {
                  onSuccess: () => showToast("Zapisano listę „Księgowi”."),
                  onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać listy."), "error"),
                })
              }
            >
              Zapisz listę
            </Button>
          </div>
        </>
      )}
    </SectionCard>
  );
}

const SALES_FIELDS: { key: keyof SalesAccounts; label: string; hint: string }[] = [
  {
    key: "receivable_account",
    label: "Rozrachunki z odbiorcami",
    hint: "konto ze słownikiem kontrahentów; analityka = ID Symfonii, gdy kontrahent nie ma konta w kartotece",
  },
  { key: "revenue_account", label: "Przychody ze sprzedaży", hint: "konto przychodów z faktur do klientów" },
  { key: "vat_account", label: "VAT należny", hint: "VAT z faktur sprzedaży" },
];
const NO_SALES_ACCOUNTS: SalesAccounts = { receivable_account: "", revenue_account: "", vat_account: "" };

function SalesAccountsCard() {
  const { config } = useAccounting();
  const { showToast } = useToast();
  const save = useSetSalesAccounts();
  const saved = config.sales_accounts ?? NO_SALES_ACCOUNTS;
  const [values, setValues] = useState<SalesAccounts>(saved);
  useEffect(() => setValues(config.sales_accounts ?? NO_SALES_ACCOUNTS), [config.sales_accounts]);
  const dirty = SALES_FIELDS.some((field) => values[field.key].trim() !== saved[field.key]);
  const complete = SALES_FIELDS.every((field) => values[field.key].trim());

  return (
    <SectionCard title="Konta faktur sprzedaży" aside={config.me.admin ? "dekret FVS ze źródeł" : "zmienia administrator"}>
      <div className="space-y-2.5 px-3.5 py-3">
        {SALES_FIELDS.map((field) => (
          <label key={field.key} className="grid grid-cols-[minmax(0,1fr)_120px] items-center gap-x-3 gap-y-0.5 text-[13px]">
            <span className="min-w-0">
              <span className="block font-medium">{field.label}</span>
              <span className={CALM_SUBLINE}>{field.hint}</span>
            </span>
            <input
              aria-label={field.label}
              className={cn(CONTROL, "w-full tabular-nums")}
              value={values[field.key]}
              disabled={!config.me.admin}
              placeholder="np. 701"
              onChange={(e) => setValues((current) => ({ ...current, [field.key]: e.target.value }))}
            />
          </label>
        ))}
        {config.me.admin ? (
          <div className="flex items-center justify-between gap-3 pt-1">
            <span className="text-[12px] text-muted-foreground">Każde konto musi być w Planie kont.</span>
            <Button
              size="sm"
              disabled={!dirty || !complete}
              loading={save.isPending}
              onClick={() =>
                save.mutate(
                  {
                    receivable_account: values.receivable_account.trim(),
                    revenue_account: values.revenue_account.trim(),
                    vat_account: values.vat_account.trim(),
                  },
                  {
                    onSuccess: () => showToast("Zapisano konta faktur sprzedaży."),
                    onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać kont."), "error"),
                  },
                )
              }
            >
              Zapisz konta
            </Button>
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}

function Years() {
  const { config, period } = useAccounting();
  const { showToast } = useToast();
  const { askConfirm, askReason, confirmDialog } = useConfirmV2();
  const createYear = useCreateYear();
  const setMode = useSetYearMode();
  const close = useClosePeriod();
  const reopen = useReopenPeriod();
  const [newYear, setNewYear] = useState(String(period.year + (config.years.some((y) => y.year === period.year) ? 1 : 0)));

  const onPeriod = async (year: LedgerYear, item: LedgerPeriod) => {
    const label = `${MONTHS_PL[item.month - 1]} ${year.year}`;
    if (item.status === "open") {
      if (!config.me.approver) return;
      if (item.drafts) {
        showToast(`W buforze są dokumenty z miesiąca ${label} (${item.drafts}) — zatwierdź albo usuń je najpierw.`, "error");
        return;
      }
      const ok = await askConfirm({
        title: `Zamknąć ${label}?`,
        description: "Zamknięty okres nie przyjmuje dokumentów ani zatwierdzeń. Otworzyć go może tylko administrator.",
        confirmLabel: "Zamknij okres",
      });
      if (!ok) return;
      close.mutate(item.id, {
        onSuccess: () => showToast(`Zamknięto ${label}.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zamknąć okresu."), "error"),
      });
      return;
    }
    if (!config.me.admin) return;
    const reason = await askReason({
      title: `Otworzyć ponownie ${label}?`,
      description: "Powód zostaje w śladzie okresu.",
      confirmLabel: "Otwórz okres",
      field: { label: "Powód", placeholder: "np. korekta faktury", minLength: 3, maxLength: 500 },
    });
    if (!reason) return;
    reopen.mutate(
      { periodId: item.id, reason },
      {
        onSuccess: () => showToast(`Otwarto ponownie ${label}.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się otworzyć okresu."), "error"),
      },
    );
  };

  const changeMode = async (year: LedgerYear, mode: YearMode) => {
    if (mode === "nexus") {
      const ok = await askConfirm({
        title: `NEXUS księgą urzędową w ${year.year}?`,
        description:
          "Tryb „NEXUS” znaczy, że dziennik NEXUSA jest księgą rachunkową firmy. Ustaw go dopiero po miesiącach równoległych zgodnych z Symfonią i po aktualizacji polityki rachunkowości.",
        confirmLabel: "Ustaw tryb NEXUS",
        variant: "destructive",
      });
      if (!ok) return;
    }
    setMode.mutate(
      { id: year.id, mode },
      {
        onSuccess: () => showToast(`Tryb roku ${year.year} zmieniony.`),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zmienić trybu."), "error"),
      },
    );
  };

  return (
    <SectionCard
      title="Rok obrotowy, tryb księgi i okresy"
      aside={config.me.approver ? "kliknij miesiąc, żeby go zamknąć" : undefined}
    >
      <div className="space-y-3 px-3.5 py-3">
        {config.years.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nie ma jeszcze żadnego roku obrotowego.</p>
        ) : null}
        {config.years.map((year) => (
          <div key={year.id} className="space-y-2 border-b border-border/60 pb-3 last:border-0 last:pb-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-display text-[17px] font-semibold tabular-nums">{year.year}</span>
              <span className="text-[12px] text-muted-foreground">pozycji dziennika: {year.journal_entries}</span>
              <select
                aria-label={`Tryb roku ${year.year}`}
                className={cn(CONTROL, "ml-auto")}
                value={year.mode}
                disabled={!config.me.admin || setMode.isPending}
                onChange={(e) => void changeMode(year, e.target.value as YearMode)}
              >
                {config.year_modes.map((mode) => (
                  <option key={mode.code} value={mode.code}>
                    {mode.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {year.periods.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => void onPeriod(year, item)}
                  title={`${MONTHS_PL[item.month - 1]}: ${item.status === "closed" ? "zamknięty" : "otwarty"} · zatwierdzone ${item.approved} · bufor ${item.drafts}`}
                  className={cn(
                    "inline-flex h-8 min-w-12 flex-col items-center justify-center rounded-md border px-2 text-[12px] tabular-nums leading-tight",
                    item.status === "closed"
                      ? "border-border bg-muted/60 text-muted-foreground"
                      : item.drafts
                        ? "border-warning/60 text-foreground"
                        : "border-border text-foreground",
                  )}
                >
                  <span className="font-semibold">{ROMAN[item.month - 1]}</span>
                </button>
              ))}
            </div>
            <p className="text-[12px] text-muted-foreground">
              Szare — zamknięte · obramowanie pomarańczowe — dokumenty w buforze.
              {config.me.admin ? " Zamknięty miesiąc otworzysz kliknięciem, z powodem." : ""}
            </p>
          </div>
        ))}
        {config.me.approver ? (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <input
              aria-label="Nowy rok obrotowy"
              className={cn(CONTROL, "w-24 tabular-nums")}
              inputMode="numeric"
              value={newYear}
              onChange={(e) => setNewYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
            />
            <Button
              size="sm"
              variant="outline"
              loading={createYear.isPending}
              disabled={newYear.length !== 4}
              onClick={() =>
                createYear.mutate(
                  { year: Number(newYear) },
                  {
                    onSuccess: () => showToast(`Założono rok obrotowy ${newYear}.`),
                    onError: (error) => showToast(apiErrorMessage(error, "Nie udało się założyć roku."), "error"),
                  },
                )
              }
            >
              Załóż rok
            </Button>
            <span className="text-[12px] text-muted-foreground">Nowy rok startuje w trybie „Symfonia FK”.</span>
          </div>
        ) : null}
      </div>
      {confirmDialog}
    </SectionCard>
  );
}
