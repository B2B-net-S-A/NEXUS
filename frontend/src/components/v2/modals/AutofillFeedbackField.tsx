"use client";

import type * as React from "react";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  AUTOFILL_REASON_GROUPS,
  autofillBucketHint,
  type AutofillLearnedFrom,
  type AutofillReason,
} from "@/lib/autofill-feedback";
import { cn } from "@/lib/utils";

/**
 * Powód odrzucenia osoby od systemu w oknie odrzucenia (makieta A3,
 * 23.10.2026): powód z trzech grup, przy „Za droga” — ile chce, skąd to
 * wiesz. Od 27.10.2026 to jedyne pytanie o powód przy takiej osobie — powód
 * z szablonu do raportu lejka liczy okno (`templateReasonFor`). Stan trzyma
 * okno (`RejectionV2`); `children` — pola pod powodem (stawka, tryb pracy).
 */
export function AutofillFeedbackField({
  learnedFrom,
  onLearnedFromChange,
  reason,
  onReasonChange,
  rate,
  onRateChange,
  rateKnown,
  several,
  askRate = true,
  children,
}: {
  learnedFrom: AutofillLearnedFrom | null;
  onLearnedFromChange: (value: AutofillLearnedFrom) => void;
  reason: AutofillReason | null;
  onReasonChange: (value: AutofillReason) => void;
  rate: string;
  onRateChange: (value: string) => void;
  /** Czy system znał stawkę w chwili dodania (jedna osoba). */
  rateKnown: boolean;
  /** Kilka osób od systemu naraz — ten sam powód, bez „Ile chce?”. */
  several: boolean;
  /** `false` — kwotę niesie pole pod powodem „za drogo” w oknie (26.10.2026). */
  askRate?: boolean;
  children?: React.ReactNode;
}) {
  const hint = autofillBucketHint(reason, rateKnown);
  return (
    <div className="space-y-3" data-testid="autofill-feedback">
      <FormField
        label="Powód"
        required
        description={`${several ? "Wśród odrzucanych są osoby od systemu" : "To osoba od systemu"} — powód trafia do raportu lejka i uczy system, co poprawić w podpowiedziach.`}
      >
        <RadioGroup
          value={reason ?? ""}
          onValueChange={(v) => onReasonChange(v as AutofillReason)}
          className="grid gap-3 sm:grid-cols-3"
        >
          {AUTOFILL_REASON_GROUPS.map((group) => (
            <fieldset key={group.title} className="space-y-1">
              <legend className="pb-1 text-xs font-semibold text-muted-foreground">{group.title}</legend>
              {group.reasons.map((r) => (
                <label
                  key={r.value}
                  className="flex cursor-pointer items-start gap-2 rounded-md p-1 text-sm hover:bg-primary/10"
                >
                  <RadioGroupItem value={r.value} className="mt-0.5" />
                  <span>{r.label}</span>
                </label>
              ))}
            </fieldset>
          ))}
        </RadioGroup>
      </FormField>
      {children}
      {reason === "too_expensive" && !several && askRate ? (
        <FormField
          label="Ile chce? (zł/h, opcjonalnie)"
          description="Zapisze się jako „Stawka od” w profilu."
        >
          <Input
            inputMode="decimal"
            value={rate}
            onChange={(e) => onRateChange(e.target.value)}
            placeholder="np. 175"
            className="w-32"
            aria-label="Ile chce w złotych na godzinę"
          />
        </FormField>
      ) : null}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      <FormField label="Skąd to wiesz?" required>
        <RadioGroup
          value={learnedFrom ?? ""}
          onValueChange={(v) => onLearnedFromChange(v as AutofillLearnedFrom)}
          className="grid gap-2 sm:grid-cols-2"
        >
          {(
            [
              { value: "profile", label: "Z CV i profilu, bez kontaktu" },
              { value: "call", label: "Z rozmowy z osobą" },
            ] as const
          ).map((o) => (
            <label
              key={o.value}
              className={cn(
                "flex cursor-pointer items-center gap-2 rounded-md border p-2 text-sm",
                learnedFrom === o.value ? "border-primary bg-primary/5" : "border-border hover:bg-accent",
              )}
            >
              <RadioGroupItem value={o.value} />
              {o.label}
            </label>
          ))}
        </RadioGroup>
      </FormField>
    </div>
  );
}

/** „175”, „175,50” → 175.5; puste albo zło → `null`. */
export function parseRateInput(raw: string): number | null {
  const value = Number(raw.trim().replace(/\s/g, "").replace(",", "."));
  return raw.trim() && Number.isFinite(value) && value > 0 && value <= 10000 ? value : null;
}
