"use client";

/**
 * Powód „Za wysokie oczekiwania finansowe” w oknie odrzucenia (prośba Marka,
 * 26.10.2026).
 *
 * Po wybraniu powodu okno pyta, ile osoba teraz chce, i pokazuje, co trafi na
 * profil. Bez tego rekruter wpisywał kwotę w opis powodu („200 minimum”,
 * „min 140 na B2B” — 51 ze 118 takich odrzuceń na kopii z 22.10.2026), a
 * „Stawka od” dalej pokazywała starą, niższą stawkę.
 */

import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { hourlyText, monthYear, toAmount } from "@/lib/candidate-rate";

import { parseRateInput } from "./AutofillFeedbackField";

/** „Stawka od” z profilu jednej osoby. */
export interface RejectionRateProfile {
  rateFromHourly: number | null;
  rateFromAt: string | null;
}

/** Co okno wysyła z ruchem, gdy wybrany jest ten powód. */
export interface RejectionRateChoice {
  rateHourly: number;
  isMinimum: boolean;
}

/** Pola ruchu `POST /api/pipeline/move` dla wyboru z okna. */
export function rejectionRateMoveFields(choice: RejectionRateChoice | null | undefined): {
  rejection_rate_hourly?: number;
  rejection_rate_is_minimum?: boolean;
} {
  return choice
    ? { rejection_rate_hourly: choice.rateHourly, rejection_rate_is_minimum: choice.isMinimum }
    : {};
}

interface Props {
  /** `undefined` — profil niewczytany, bez linii „Teraz w profilu”. */
  profile?: RejectionRateProfile | null;
  rate: string;
  onRateChange: (value: string) => void;
  isMinimum: boolean;
  onIsMinimumChange: (value: boolean) => void;
}

export function RejectionRateField({
  profile,
  rate,
  onRateChange,
  isMinimum,
  onIsMinimumChange,
}: Props) {
  const value = parseRateInput(rate);
  const current = toAmount(profile?.rateFromHourly);
  const currentText = current !== null ? hourlyText(current) : null;
  const currentWhen = monthYear(profile?.rateFromAt ?? null);
  const lower = value !== null && current !== null && value < current - 0.005;

  return (
    <div
      data-testid="rejection-rate"
      className="ml-6 space-y-2 rounded-md border border-border border-l-2 border-l-primary px-3 py-2.5"
    >
      <FormField label="Ile teraz chce? (zł/h, opcjonalnie)">
        <div className="flex items-center gap-2">
          <Input
            inputMode="decimal"
            value={rate}
            onChange={(e) => onRateChange(e.target.value)}
            placeholder="np. 150"
            className="w-28"
            aria-label="Ile teraz chce w złotych na godzinę"
          />
          <span className="text-sm text-muted-foreground">zł/h netto na B2B</span>
        </div>
      </FormField>
      {lower ? (
        <p className="text-xs text-warning-muted-foreground">
          To mniej niż obecna „Stawka od” ({currentText}) — sprawdź kwotę.
        </p>
      ) : null}

      <label className="flex cursor-pointer items-start gap-2 rounded-md p-1.5 text-sm hover:bg-primary/10">
        <input
          type="checkbox"
          className="mt-0.5 h-4 w-4 rounded border-[hsl(var(--border))] text-primary focus:ring-primary"
          checked={isMinimum}
          onChange={(e) => onIsMinimumChange(e.target.checked)}
          disabled={value === null}
        />
        <span>
          To jego nowe minimum — zapisz w profilu:{" "}
          <span className="font-medium">
            Stawka od {currentText ? `${currentText} → ` : "→ "}
            {value !== null ? hourlyText(value) : "…"}
          </span>
          <span className="block text-xs text-muted-foreground">
            {profile !== undefined
              ? `Teraz w profilu: ${currentText ? `od ${currentText}${currentWhen ? ` (${currentWhen})` : ""}` : "brak stawki"}. `
              : ""}
            Starsze niższe stawki przestaną się liczyć; zostaną w historii stawek.
          </span>
        </span>
      </label>
    </div>
  );
}
