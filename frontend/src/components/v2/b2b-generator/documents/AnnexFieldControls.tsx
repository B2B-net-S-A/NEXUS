"use client";

// Kontrolki generatora aneksów, których nie da się opisać jednym polem:
// pozycje stawki (kwota, klient z NEXUSA, od, do) i „Pobierz z CEIDG/KRS”
// przy NIP. Reguły (walidacja, przepisanie pól rejestru) żyją w
// `lib/b2b-documents.ts` — tu jest tylko widok.

import { useState } from "react";
import { Loader2, Plus, Search, Trash2 } from "lucide-react";

import { ClientSinglePicker } from "@/components/clients/ClientSinglePicker";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { b2bGeneratorApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import type {
  DocumentFieldDef,
  DocumentValues,
  RateItemValue,
} from "@/lib/api/b2bDocuments";
import { seatLocativePl } from "@/lib/b2b-company-variant";
import {
  MAX_RATE_ITEMS,
  emptyRateItem,
  registryLookupValues,
} from "@/lib/b2b-documents";
import { cn } from "@/lib/utils";

export function RateItemsField({
  id,
  value,
  onChange,
  disabled,
  invalid,
  describedBy,
}: {
  id: string;
  value: RateItemValue[];
  onChange: (next: RateItemValue[]) => void;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string;
}) {
  const items = value.length ? value : [emptyRateItem()];
  const update = (index: number, patch: Partial<RateItemValue>) =>
    onChange(items.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  return (
    <div
      id={id}
      role="group"
      aria-describedby={describedBy}
      className={cn("space-y-3", invalid && "rounded-lg ring-2 ring-destructive p-2")}
    >
      {items.map((item, index) => {
        const rowId = `${id}-${index}`;
        const text =
          item.rate === null || item.rate === undefined ? "" : String(item.rate);
        return (
          <div
            key={index}
            className="grid gap-3 rounded-lg border border-border p-3 sm:grid-cols-2 lg:grid-cols-[140px_minmax(0,1fr)_150px_150px_auto] lg:items-end"
          >
            <div className="space-y-1">
              <Label htmlFor={`${rowId}-rate`} className="text-xs font-medium">
                Stawka netto (zł/h) *
              </Label>
              <Input
                id={`${rowId}-rate`}
                inputMode="decimal"
                placeholder="np. 135"
                value={text}
                disabled={disabled}
                onChange={(e) => update(index, { rate: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <span className="text-xs font-medium">Klient B2BNET (opcjonalnie)</span>
              <ClientSinglePicker
                queryKey="b2b-annex-rate-clients"
                allowClear
                disabled={disabled}
                placeholder="Bez wskazania klienta"
                value={
                  item.client_id
                    ? { id: item.client_id, name: item.client_name ?? `Klient #${item.client_id}` }
                    : null
                }
                onChange={(client) =>
                  update(index, {
                    client_id: client?.id ?? null,
                    client_name: client?.name ?? null,
                  })
                }
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`${rowId}-from`} className="text-xs font-medium">
                Od (opcjonalnie)
              </Label>
              <Input
                id={`${rowId}-from`}
                type="date"
                value={item.from ?? ""}
                disabled={disabled}
                onChange={(e) => update(index, { from: e.target.value || null })}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`${rowId}-to`} className="text-xs font-medium">
                Do (opcjonalnie)
              </Label>
              <Input
                id={`${rowId}-to`}
                type="date"
                value={item.to ?? ""}
                disabled={disabled}
                onChange={(e) => update(index, { to: e.target.value || null })}
              />
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="justify-self-start"
              disabled={disabled || items.length === 1}
              aria-label={`Usuń pozycję stawki ${index + 1}`}
              title="Usuń pozycję"
              onClick={() => onChange(items.filter((_, i) => i !== index))}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || items.length >= MAX_RATE_ITEMS}
        onClick={() => onChange([...items, emptyRateItem()])}
      >
        <Plus className="mr-1 h-4 w-4" aria-hidden="true" />
        Dodaj stawkę
      </Button>
    </div>
  );
}

/** „Pobierz z CEIDG/KRS” — dane z rejestru do pól formularza (do poprawy). */
export function RegistryLookupButton({
  field,
  nip,
  onFill,
  disabled,
}: {
  field: DocumentFieldDef;
  nip: string;
  onFill: (values: DocumentValues) => void;
  disabled?: boolean;
}) {
  const [state, setState] = useState<
    { kind: "idle" } | { kind: "loading" } | { kind: "done"; filled: number } | { kind: "error"; message: string }
  >({ kind: "idle" });
  const company = field.lookup_fills.some(([source]) => source === "krs");
  const label = company ? "Pobierz z KRS" : "Pobierz z CEIDG";
  const digits = nip.replace(/\D/g, "");
  const run = async () => {
    setState({ kind: "loading" });
    try {
      const data = await b2bGeneratorApi.companyLookup({ nip: digits });
      const values = registryLookupValues(
        field.lookup_fills,
        data as unknown as Record<string, unknown>,
        (city) => seatLocativePl(city).phrase,
      );
      onFill(values);
      setState({ kind: "done", filled: Object.keys(values).length });
    } catch (error) {
      setState({
        kind: "error",
        message: apiErrorMessage(error, "Nie udało się pobrać danych z rejestru."),
      });
    }
  };
  return (
    <div className="space-y-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || digits.length !== 10 || state.kind === "loading"}
        onClick={() => void run()}
      >
        {state.kind === "loading" ? (
          <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden="true" />
        ) : (
          <Search className="mr-1 h-4 w-4" aria-hidden="true" />
        )}
        {label}
      </Button>
      <p role="status" className="text-xs">
        {state.kind === "done" ? (
          <span className="text-muted-foreground">
            {state.filled
              ? "Uzupełniono z rejestru — sprawdź dane przed wygenerowaniem."
              : "Rejestr nie zwrócił nowych danych."}
          </span>
        ) : state.kind === "error" ? (
          <span className="text-destructive">{state.message}</span>
        ) : digits.length !== 10 ? (
          <span className="text-muted-foreground">Wpisz 10 cyfr NIP.</span>
        ) : null}
      </p>
    </div>
  );
}
