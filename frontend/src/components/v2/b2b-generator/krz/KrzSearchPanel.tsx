"use client";

import * as React from "react";
import { ExternalLink } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { B2BKrzEntryKind } from "@/lib/api";
import {
  KRZ_ENTRY_KINDS,
  KRZ_NOTE_MAX,
  KRZ_PORTAL_URL,
  digitsOnly,
  peselLooksValid,
  type KrzFormState,
} from "@/lib/b2b-krz";

interface KrzSearchPanelProps {
  /** NIP Partnera z formularza albo z wiersza rejestru. */
  nip: string;
  value: KrzFormState;
  onChange: (next: KrzFormState) => void;
  disabled?: boolean;
}

const RESULT_OPTIONS = [
  { value: "clear", label: "Brak wpisów" },
  {
    value: "entry",
    label: "Jest wpis",
    checkedClassName: "bg-destructive text-destructive-foreground",
  },
] as const;

/**
 * Sprawdzenie Partnera w KRZ: dwa wyszukiwania w portalu (firma po NIP-ie,
 * osoba po PESEL-u) i wynik zaznaczony przez człowieka. PESEL żyje tylko w tym
 * komponencie — nie trafia do formularza umowy, API ani bazy.
 */
export function KrzSearchPanel({ nip, value, onChange, disabled }: KrzSearchPanelProps) {
  const toast = useToast();
  const [pesel, setPesel] = React.useState("");
  const peselId = React.useId();
  const resultId = React.useId();
  const kindId = React.useId();
  const noteId = React.useId();
  const nipDigits = digitsOnly(nip);
  const peselDigits = digitsOnly(pesel);
  const peselTypo = peselDigits.length === 11 && !peselLooksValid(peselDigits);

  const openPortal = async (number: string, what: string) => {
    try {
      await navigator.clipboard.writeText(number);
      toast.showInfo(`Skopiowano ${what}. Wklej go w wyszukiwarce KRZ.`);
    } catch {
      toast.showInfo(`Wpisz w wyszukiwarce KRZ ${what}: ${number}`);
    }
    window.open(KRZ_PORTAL_URL, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="space-y-3" data-testid="krz-search-panel">
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="space-y-1">
          <span className="block text-xs font-medium text-muted-foreground">
            Firma po NIP-ie
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full justify-between"
            disabled={disabled || nipDigits.length !== 10}
            onClick={() => void openPortal(nipDigits, "NIP")}
          >
            <span className="tabular-nums">
              {nipDigits.length === 10 ? `Otwórz KRZ: NIP ${nipDigits}` : "Najpierw wpisz NIP"}
            </span>
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </div>
        <div className="space-y-1">
          <label htmlFor={peselId} className="block text-xs font-medium text-muted-foreground">
            Osoba po PESEL-u (upadłość konsumencka, alimenty)
          </label>
          <div className="flex gap-2">
            <Input
              id={peselId}
              inputMode="numeric"
              autoComplete="off"
              placeholder="PESEL Partnera"
              value={pesel}
              maxLength={11}
              disabled={disabled}
              onChange={(e) => setPesel(digitsOnly(e.target.value))}
              className="tabular-nums"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled || peselDigits.length !== 11}
              onClick={() => void openPortal(peselDigits, "PESEL")}
              aria-label="Otwórz KRZ z PESEL-em"
            >
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </Button>
          </div>
          <p className="text-[11px] text-muted-foreground">
            {peselTypo
              ? "Ten PESEL ma złą cyfrę kontrolną, sprawdź literówkę."
              : "NEXUS nie zapisuje PESEL-u, służy tylko do wyszukania."}
          </p>
        </div>
      </div>

      <div className="space-y-1">
        <span id={resultId} className="block text-xs font-medium text-muted-foreground">
          Wynik w KRZ
        </span>
        <SegmentedRadio
          labelledBy={resultId}
          size="sm"
          options={RESULT_OPTIONS}
          value={value.result}
          disabled={disabled}
          onChange={(result) =>
            onChange({
              ...value,
              result,
              entryKind: result === "clear" ? null : value.entryKind,
              entryNote: result === "clear" ? "" : value.entryNote,
            })
          }
        />
      </div>

      {value.result === "entry" ? (
        <div className="grid gap-2 sm:grid-cols-2" data-testid="krz-entry-fields">
          <div className="space-y-1">
            <label htmlFor={kindId} className="block text-xs font-medium text-muted-foreground">
              Rodzaj wpisu
            </label>
            <Select
              value={value.entryKind ?? undefined}
              disabled={disabled}
              onValueChange={(kind) =>
                onChange({ ...value, entryKind: kind as B2BKrzEntryKind })
              }
            >
              <SelectTrigger id={kindId}>
                <SelectValue placeholder="Wybierz rodzaj wpisu" />
              </SelectTrigger>
              <SelectContent>
                {KRZ_ENTRY_KINDS.map((k) => (
                  <SelectItem key={k.value} value={k.value}>
                    {k.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label htmlFor={noteId} className="block text-xs font-medium text-muted-foreground">
              Sygnatura albo krótki opis
            </label>
            <Input
              id={noteId}
              value={value.entryNote}
              maxLength={KRZ_NOTE_MAX}
              disabled={disabled}
              placeholder="np. GW1K/GUp/12/2025"
              onChange={(e) => onChange({ ...value, entryNote: e.target.value })}
            />
          </div>
          <p className="text-xs text-muted-foreground sm:col-span-2">
            Umowę pobierzesz, ale do podpisu pójdzie po decyzji Delivery Leada klienta.
          </p>
        </div>
      ) : null}
    </div>
  );
}
