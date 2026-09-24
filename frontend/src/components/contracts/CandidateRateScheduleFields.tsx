"use client";

import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn, sanitizeDecimalInput } from "@/lib/utils";
import { type RateScheduleRow } from "@/lib/contract-rate-schedule";

interface Props {
  rows: RateScheduleRow[];
  onChange: (rows: RateScheduleRow[]) => void;
  /** Data rozpoczęcia kontraktu — domyślne „Obowiązuje od" pierwszego etapu. */
  startDate: string;
  /** Nagłówek sekcji (domyślnie „Stawka kandydata"). */
  label?: string;
  /** Podpowiedź obok nagłówka. */
  hint?: string;
  /** Tekst przycisku dodania etapu. */
  addLabel?: string;
}

const DEFAULT_HINT =
  "Możesz zaplanować progresję stawki — system zastosuje aktualną od wskazanej daty.";

/**
 * Progresywna stawka — lista etapów `{ Stawka, Obowiązuje od, Obowiązuje do }`
 * wprowadzana przy tworzeniu kontraktu. „Obowiązuje do" jest edytowalne (można
 * wpisać konkretną datę końcową); pozostawione puste wylicza się automatycznie z
 * początku kolejnego etapu, a ostatni etap „bezterminowo" (patrz
 * `buildCandidateRateSchedule`). Domyślne etykiety opisują stawkę kandydata;
 * `label`/`hint`/`addLabel` pozwalają użyć tego samego edytora dla stawki z umowy
 * ramowej. Współdzielone przez `/contracts/new` i rejestr per-klient.
 */
export function CandidateRateScheduleFields({
  rows,
  onChange,
  startDate,
  label = "Stawka kandydata",
  hint = DEFAULT_HINT,
  addLabel = "+ Dodaj stawkę progresywną",
}: Props) {
  const patchRow = (idx: number, patch: Partial<RateScheduleRow>) =>
    onChange(rows.map((row, i) => (i === idx ? { ...row, ...patch } : row)));

  const addRow = () => onChange([...rows, { rate: "", effectiveFrom: "" }]);

  const removeRow = (idx: number) =>
    onChange(rows.filter((_, i) => i !== idx));

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <Label className="block">{label}</Label>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </div>

      <div className="space-y-2">
        {rows.map((row, idx) => (
          // Na telefonie etap to karta z polami jedno pod drugim (trzy pola w
          // wierszu dawały ~70 px na datę); od `sm` jeden wiersz jak dotąd.
          <div
            key={idx}
            className="grid grid-cols-1 gap-2 rounded-md border border-border p-2 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end sm:border-0 sm:p-0"
          >
            <div className="flex-1">
              <span
                className={cn(
                  "mb-1 block text-xs text-muted-foreground",
                  idx > 0 && "sm:hidden",
                )}
              >
                Stawka
              </span>
              <Input
                type="text"
                inputMode="decimal"
                value={row.rate}
                onChange={(e) =>
                  patchRow(idx, { rate: sanitizeDecimalInput(e.target.value) })
                }
                placeholder="np. 215,60"
              />
            </div>
            <div className="flex-1">
              <span
                className={cn(
                  "mb-1 block text-xs text-muted-foreground",
                  idx > 0 && "sm:hidden",
                )}
              >
                Obowiązuje od
              </span>
              <Input
                type="date"
                value={row.effectiveFrom}
                onChange={(e) => patchRow(idx, { effectiveFrom: e.target.value })}
                placeholder={idx === 0 ? "= data rozpoczęcia" : ""}
              />
            </div>
            <div className="flex-1">
              <span
                className={cn(
                  "mb-1 block text-xs text-muted-foreground",
                  idx > 0 && "sm:hidden",
                )}
              >
                Obowiązuje do
              </span>
              <Input
                type="date"
                value={row.effectiveTo ?? ""}
                min={row.effectiveFrom || startDate || undefined}
                onChange={(e) => patchRow(idx, { effectiveTo: e.target.value })}
                aria-label="Obowiązuje do"
              />
            </div>
            {idx > 0 ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                title="Usuń etap stawki"
                aria-label={`Usuń etap ${idx + 1} stawki`}
                className="justify-self-end"
                onClick={() => removeRow(idx)}
              >
                <X className="h-4 w-4" />
              </Button>
            ) : (
              <span className="hidden w-9 shrink-0 sm:block" aria-hidden />
            )}
          </div>
        ))}
      </div>

      <Button type="button" variant="outline" size="sm" onClick={addRow}>
        {addLabel}
      </Button>

      {rows[0]?.effectiveFrom === "" && (
        <p className="text-xs text-muted-foreground">
          Pierwszy etap bez daty obowiązuje od daty rozpoczęcia kontraktu.
        </p>
      )}
      {rows.length > 1 && (
        <p className="text-xs text-muted-foreground">
          Puste „Obowiązuje do" wylicza się automatycznie: etap trwa do dnia
          przed kolejnym etapem, a ostatni — bezterminowo.
        </p>
      )}
    </div>
  );
}
