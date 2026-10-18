"use client";

import { useState } from "react";
import { Trash2, Wallet } from "lucide-react";

import { useToast } from "@/components/Toast";
import { BonusRulesCard } from "@/components/hr/payroll/BonusRulesCard";
import { parseAmount } from "@/components/hr/payroll/payroll-format";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import type { HrConfig } from "@/lib/api/hr";
import { useMinimumRates, useSaveMinimumRates, type MinimumRates } from "@/lib/api/hr-payroll";
import { resolveViewState } from "@/lib/view-state";

import { KsefStatusCard } from "@/components/hr/payroll/ksef/KsefStatusCard";

import { PaymentSettingsCard } from "./PaymentSettingsCard";

/** Kto zmienia reguły premii — lustro `require_hr_payroll_admin` (Płace, admin zawsze). */
export function canEditPayrollSettings(config: Pick<HrConfig, "me">): boolean {
  return config.me.payroll || config.me.is_admin;
}

export interface MinimumRow {
  year: string;
  rate: string;
}

export function rowsFromRates(data: MinimumRates | undefined): MinimumRow[] {
  return (data?.rates ?? []).map((row) => ({
    year: String(row.year),
    rate: String(Number(row.hourly_rate).toFixed(2)).replace(".", ","),
  }));
}

/**
 * Wiersze formularza → ciało `PUT /settings/minimum-rates` albo zdanie błędu
 * (rok 2020–2100, kwota większa od zera, bez powtórzonych lat). Serwer
 * sprawdza to samo — tu, żeby błąd był widać przed zapisem.
 */
export function minimumRatesPayload(
  rows: readonly MinimumRow[],
): { rates: Record<string, string> } | { error: string } {
  const rates: Record<string, string> = {};
  for (const row of rows) {
    const year = Number(row.year.trim());
    if (!Number.isInteger(year) || year < 2020 || year > 2100) {
      return { error: "Rok minimalnej stawki: od 2020 do 2100." };
    }
    const amount = parseAmount(row.rate);
    if (amount === null || Number(amount) <= 0) {
      return { error: `Minimalna stawka w ${year}: kwota większa od zera, np. 31,40.` };
    }
    if (String(year) in rates) return { error: `Rok ${year} jest na liście dwa razy.` };
    rates[String(year)] = amount;
  }
  return { rates };
}

/**
 * Minimalna stawka godzinowa na zleceniu (etap 2, D7): tabela lat z Ustawień.
 * Stawka osoby na zleceniu poniżej minimum roku „od” nie zapisze się (422);
 * rok bez minimum = zapis z ostrzeżeniem. Nowy rok dopisują Płace bez wdrożenia.
 */
function MinimumRatesCard() {
  const rates = useMinimumRates();
  const save = useSaveMinimumRates();
  const { showToast } = useToast();
  const [rows, setRows] = useState<MinimumRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const state = resolveViewState({
    isLoading: rates.isLoading,
    isError: rates.isError,
    error: rates.error,
    isSuccess: rates.isSuccess,
  });
  if (state === "forbidden" || state === "not_found") return null;
  const shown = rows ?? rowsFromRates(rates.data);
  const update = (index: number, patch: Partial<MinimumRow>) =>
    setRows(shown.map((row, at) => (at === index ? { ...row, ...patch } : row)));

  const submit = () => {
    const parsed = minimumRatesPayload(shown);
    if ("error" in parsed) {
      setError(parsed.error);
      return;
    }
    setError(null);
    save.mutate(parsed.rates, {
      onSuccess: () => {
        setRows(null);
        showToast("Minimalne stawki zapisane", "success");
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać stawek.")),
    });
  };

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
          Minimalna stawka na zleceniu
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Zł/h brutto na każdy rok (ustawa o minimalnym wynagrodzeniu). Stawka osoby na zleceniu
          poniżej minimum roku, od którego obowiązuje, nie zapisze się.
        </p>
      </div>
      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie stawek…</p>
      ) : state === "error" ? (
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          Nie udało się wczytać stawek.
          <Button size="sm" variant="ghost" onClick={() => rates.refetch()}>
            Spróbuj ponownie
          </Button>
        </div>
      ) : (
        <>
          <ul className="space-y-2">
            {shown.map((row, index) => (
              <li key={index} className="flex flex-wrap items-center gap-2">
                <Input
                  aria-label="Rok"
                  inputMode="numeric"
                  className="h-8 w-24"
                  value={row.year}
                  onChange={(event) => update(index, { year: event.target.value })}
                />
                <Input
                  aria-label={`Minimalna stawka w ${row.year || "roku"}`}
                  inputMode="decimal"
                  className="h-8 w-28"
                  value={row.rate}
                  onChange={(event) => update(index, { rate: event.target.value })}
                />
                <span className="text-sm text-muted-foreground">zł/h brutto</span>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={`Usuń rok ${row.year}`}
                  onClick={() => setRows(shown.filter((_, at) => at !== index))}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                const last = Math.max(0, ...shown.map((row) => Number(row.year) || 0));
                setRows([...shown, { year: last ? String(last + 1) : "", rate: "" }]);
              }}
            >
              Dodaj rok
            </Button>
            <Button onClick={submit} disabled={save.isPending || rows === null}>
              {save.isPending ? "Zapisywanie…" : "Zapisz stawki"}
            </Button>
          </div>
        </>
      )}
    </Card>
  );
}

/**
 * Ustawienia → Zespół i dostęp → Płace (17.10.2026): reguły premii
 * z placementów i z Ligi. Do 17.10 karta stała w „Kadrach”, do których osoba
 * z samym uprawnieniem „Płace” (Finanse) nie wchodziła, choć API ją wpuszczało.
 */
export function PayrollSettings({ config }: { config: HrConfig }) {
  if (!canEditPayrollSettings(config)) {
    return (
      <div className="p-6 text-muted-foreground">
        Reguły premii zmienia osoba z uprawnieniem „Płace” albo administrator.
      </div>
    );
  }
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-foreground">
          <Wallet className="h-5 w-5 text-primary" aria-hidden />
          Płace
        </h1>
        <p className="text-sm text-muted-foreground">
          Reguły premii z placementów i z Ligi Mistrzów, minimalna stawka na zleceniu. Stawki
          i premie osób są w „Ludzie → Płace”.
        </p>
      </div>
      {config.open_modules.payroll ? (
        <>
          <BonusRulesCard />
          <MinimumRatesCard />
          {config.open_modules.settlements ? <PaymentSettingsCard /> : null}
          {config.open_modules.settlements ? <KsefStatusCard /> : null}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Moduł płac nie jest jeszcze włączony — reguły premii ustawisz po jego włączeniu
          (Ustawienia → Kadry → „Moduły”).
        </p>
      )}
    </div>
  );
}
