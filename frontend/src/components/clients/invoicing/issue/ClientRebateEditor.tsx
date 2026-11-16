"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { IssueCurrency, RebateTerms, RebateTier } from "@/lib/api/issued-invoices";

const CURRENCIES: IssueCurrency[] = ["PLN", "EUR", "USD"];
const SELECT =
  "h-10 w-full rounded-lg border border-border bg-card px-3 text-sm text-foreground";

function numberOrNull(raw: string): number | null {
  const value = Number(raw.replace(/\s/g, "").replace(",", "."));
  return raw.trim() === "" || Number.isNaN(value) ? null : value;
}

/**
 * Pole kwoty/stawki: trzyma wpisany tekst („2,” w trakcie pisania „2,5”), a do
 * danych oddaje liczbę. Bez tego liczba gubi przecinek i „2,5” robi się 25.
 */
function DecimalInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label: string;
  value: number | null;
  placeholder?: string;
  onChange: (value: number | null) => void;
}) {
  const [text, setText] = useState(value === null ? "" : String(value).replace(".", ","));
  return (
    <Input
      aria-label={label}
      inputMode="decimal"
      placeholder={placeholder}
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(numberOrNull(e.target.value));
      }}
    />
  );
}

/**
 * Rabat od obrotu rocznego z umowy ramowej (decyzje Artura 16.11.2026): progi
 * i stawki jako dane przy kliencie, okres „od roku”, próg w walucie umowy.
 * Rabat % idzie na wierszach usług po stawce z obrotu sprzed miesiąca;
 * wyższa stawka tylko od nadwyżki ponad próg.
 */
export function ClientRebateEditor({
  label,
  value,
  onChange,
}: {
  label: string;
  value: RebateTerms | undefined;
  onChange: (value: RebateTerms | undefined) => void;
}) {
  if (!value) {
    return (
      <div className="md:col-span-4">
        <Button
          size="sm"
          variant="ghost"
          onClick={() =>
            onChange({
              threshold_currency: "PLN",
              periods: [
                {
                  from_year: new Date().getFullYear(),
                  tiers: [{ up_to: null, rate: 0 }],
                },
              ],
              exclude_words: [],
            })
          }
        >
          <Plus className="mr-1 h-4 w-4" aria-hidden />
          Rabat roczny od obrotu
        </Button>
      </div>
    );
  }

  const setPeriod = (index: number, patch: Partial<RebateTerms["periods"][number]>) =>
    onChange({
      ...value,
      periods: value.periods.map((period, i) => (i === index ? { ...period, ...patch } : period)),
    });
  const setTier = (periodIndex: number, tierIndex: number, patch: Partial<RebateTier>) =>
    setPeriod(periodIndex, {
      tiers: value.periods[periodIndex].tiers.map((tier, i) =>
        i === tierIndex ? { ...tier, ...patch } : tier,
      ),
    });
  const last = value.periods[value.periods.length - 1];

  return (
    <fieldset className="grid gap-2 rounded-lg border border-border/60 px-3 py-2 md:col-span-4">
      <legend className="px-1 text-xs font-semibold text-foreground">Rabat roczny od obrotu</legend>
      <p className="text-xs text-muted-foreground">
        Każda faktura z „Wystaw za miesiąc” dostaje rabat % na wierszach usług (jak w eBI24) po stawce progu,
        w którym jest obrót roku przed rabatem (z KSeF) do końca poprzedniego miesiąca. Wyższa stawka dotyczy tylko
        nadwyżki ponad próg — za miesiąc przekroczenia karta faktury pokazuje kwotę korekty.
      </p>
      <div className="grid gap-2 md:grid-cols-[10rem_minmax(0,1fr)]">
        <label className="grid gap-1 text-xs text-muted-foreground">
          Waluta progu
          <select
            aria-label={`Waluta progu rabatu — ${label}`}
            className={SELECT}
            value={value.threshold_currency}
            onChange={(e) => onChange({ ...value, threshold_currency: e.target.value as IssueCurrency })}
          >
            {CURRENCIES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          Poza obrotem faktury, których każda pozycja zawiera słowo (po przecinku)
          <Input
            aria-label={`Słowa wyłączające z rabatu — ${label}`}
            placeholder="np. podróż, refaktura"
            value={value.exclude_words.join(", ")}
            onChange={(e) =>
              onChange({
                ...value,
                exclude_words: e.target.value.split(",").map((word) => word.trimStart()),
              })
            }
          />
        </label>
      </div>
      {value.periods.map((period, periodIndex) => (
        <div key={`${periodIndex}/${value.periods.length}`} className="grid gap-2 rounded-md bg-muted/40 px-2 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Od roku</span>
            <Input
              aria-label={`Rabat od roku — ${label}`}
              className="w-24"
              type="number"
              min={2020}
              max={2100}
              value={period.from_year}
              onChange={(e) => setPeriod(periodIndex, { from_year: Number(e.target.value) })}
            />
            {value.periods.length > 1 ? (
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Usuń okres rabatu od ${period.from_year}`}
                onClick={() =>
                  onChange({ ...value, periods: value.periods.filter((_, i) => i !== periodIndex) })
                }
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            ) : null}
          </div>
          {period.tiers.map((tier, tierIndex) => (
            <div key={`${tierIndex}/${period.tiers.length}`} className="grid items-center gap-2 sm:grid-cols-[minmax(0,1fr)_8rem_2.5rem]">
              <DecimalInput
                label={`Próg ${tierIndex + 1}: obrót do (${value.threshold_currency}) — ${label}`}
                placeholder="bez górnej granicy"
                value={tier.up_to}
                onChange={(up_to) => setTier(periodIndex, tierIndex, { up_to })}
              />
              <DecimalInput
                label={`Próg ${tierIndex + 1}: stawka % — ${label}`}
                value={tier.rate}
                onChange={(rate) => setTier(periodIndex, tierIndex, { rate: rate ?? 0 })}
              />
              <Button
                size="sm"
                variant="ghost"
                aria-label={`Usuń próg ${tierIndex + 1}`}
                disabled={period.tiers.length === 1}
                onClick={() =>
                  setPeriod(periodIndex, { tiers: period.tiers.filter((_, i) => i !== tierIndex) })
                }
              >
                <Trash2 className="h-4 w-4" aria-hidden />
              </Button>
            </div>
          ))}
          <div>
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                setPeriod(periodIndex, { tiers: [...period.tiers, { up_to: null, rate: 0 }] })
              }
            >
              <Plus className="mr-1 h-4 w-4" aria-hidden />
              Próg
            </Button>
          </div>
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() =>
            onChange({
              ...value,
              periods: [
                ...value.periods,
                { from_year: last.from_year + 1, tiers: last.tiers.map((tier) => ({ ...tier })) },
              ],
            })
          }
        >
          Nowe progi od roku (aneks)
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onChange(undefined)}>
          Usuń rabat
        </Button>
      </div>
    </fieldset>
  );
}
