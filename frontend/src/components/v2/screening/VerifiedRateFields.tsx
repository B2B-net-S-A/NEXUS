"use client";

/**
 * Pola „stawki oczekiwanej" wraz z werdyktem bramki budżetowej — wspólne dla
 * modala `VerifiedRateModal` (ruch z tablicy) i doku „Weryfikacja" na
 * stanowisku screeningu (krok 05 programu „flow w języku C2", PR 6/7).
 *
 * Makieta kroku 05 pokazuje stawkę INLINE w doku, z komunikatem „mieści się
 * w budżecie / czeka na akceptację" widocznym ZANIM ktoś kliknie. To ten sam
 * werdykt, który modal pokazuje po wpisaniu kwoty, więc pola i zdanie pod nimi
 * są jednym komponentem, a sama reguła — jedną funkcją (`evaluateRateGate`).
 */

import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { RateUnit } from "@/lib/api";
import {
  RATE_UNIT_LABELS,
  type RateGateResult,
} from "@/lib/verified-rate-gate";

export interface VerifiedRateFieldsProps {
  /** Surowa treść pola — walidację robi `evaluateRateGate`, nie input. */
  rate: string;
  onRateChange: (value: string) => void;
  unit: RateUnit;
  onUnitChange: (unit: RateUnit) => void;
  gate: RateGateResult;
  disabled?: boolean;
  autoFocus?: boolean;
  /** Enter w polu kwoty = zatwierdź (modal). Pomijalne. */
  onSubmit?: () => void;
  /** Unikalne id — dwa te same pola potrafią stać na jednym ekranie. */
  idPrefix?: string;
}

/** Kolory i ikona werdyktu — wyłącznie tokeny DS, zero hardcodów palety. */
const VERDICT_STYLE = {
  within_budget: {
    icon: CheckCircle2,
    className:
      "border-success/30 bg-success-muted text-success-muted-foreground",
  },
  needs_approval: {
    icon: AlertTriangle,
    className:
      "border-warning/30 bg-warning-muted text-warning-muted-foreground",
  },
  no_budget: {
    icon: Info,
    className: "border-border bg-muted/40 text-muted-foreground",
  },
} as const;

export function VerifiedRateFields({
  rate,
  onRateChange,
  unit,
  onUnitChange,
  gate,
  disabled,
  autoFocus,
  onSubmit,
  idPrefix = "verified-rate",
}: VerifiedRateFieldsProps) {
  const rateId = `${idPrefix}-value`;
  const unitId = `${idPrefix}-unit`;
  const verdict = VERDICT_STYLE[gate.verdict];
  const VerdictIcon = verdict.icon;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-[1.2fr_minmax(0,1fr)] gap-3">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={rateId}>Kwota</Label>
          <input
            id={rateId}
            type="number"
            inputMode="decimal"
            step="0.01"
            min="0"
            value={rate}
            disabled={disabled}
            onChange={(e) => onRateChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && onSubmit && gate.isValid) {
                e.preventDefault();
                onSubmit();
              }
            }}
            placeholder="np. 118"
            className="h-10 w-full rounded-md border border-border bg-card px-3 focus:outline-hidden focus:ring-2 focus:ring-primary disabled:cursor-not-allowed disabled:opacity-60"
            autoFocus={autoFocus}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={unitId}>Jednostka</Label>
          <Select
            value={unit}
            onValueChange={(v) => onUnitChange(v as RateUnit)}
            disabled={disabled}
          >
            <SelectTrigger id={unitId} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(RATE_UNIT_LABELS) as RateUnit[]).map((u) => (
                <SelectItem key={u} value={u}>
                  {RATE_UNIT_LABELS[u]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {gate.message && (
        <div
          className={cn(
            "flex items-start gap-2 rounded-md border px-3 py-2 text-xs",
            verdict.className,
          )}
          // Zmiana werdyktu w trakcie pisania musi dojść do czytnika ekranu —
          // to jedyny sygnał, że ruch pójdzie do akceptacji zamiast przejść.
          role="status"
        >
          <VerdictIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          <span>{gate.message}</span>
        </div>
      )}

      <p className="text-[11px] text-muted-foreground">
        Porównanie idzie po jednostce miesięcznej: godzina × 168, dzień × 21.
        Waluta inna niż PLN albo nieznana jednostka → akceptacja ręczna.
      </p>
    </div>
  );
}
