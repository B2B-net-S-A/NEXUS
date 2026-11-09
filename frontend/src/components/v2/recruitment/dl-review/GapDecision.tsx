"use client";

/**
 * Luka kandydata przy wysyłce (QC-8, 08.11.2026): krytyczna, której osoba nie
 * ma, to decyzja Delivery Leada. Wybór jest obowiązkowy i zostaje w historii
 * (`gap_decision`), bo za miesiąc trzeba móc ocenić, czy takie wysyłki działają.
 */

import { useId } from "react";

import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

export type GapChoice = "send" | "return";

export interface GapDecisionProps {
  gaps: readonly string[];
  value: GapChoice | null;
  onChange: (value: GapChoice) => void;
}

export function GapDecision({ gaps, value, onChange }: GapDecisionProps) {
  const id = useId();
  const names = gaps.join(", ");
  return (
    <section aria-label="Decyzja o luce kandydata" className="space-y-1.5 rounded-lg border border-warning/40 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
      <p className="font-medium">Kandydat nie ma: {names} (krytyczna).</p>
      <RadioGroup value={value ?? ""} onValueChange={(next) => onChange(next as GapChoice)} aria-label="Co robisz z tą luką?">
        <label htmlFor={`${id}-send`} className="flex cursor-pointer items-center gap-2">
          <RadioGroupItem id={`${id}-send`} value="send" />
          Wysyłam mimo braku: {names}
        </label>
        <label htmlFor={`${id}-return`} className="flex cursor-pointer items-center gap-2">
          <RadioGroupItem id={`${id}-return`} value="return" />
          Wracam do rekrutera
        </label>
      </RadioGroup>
      {value === "return" ? <p>Użyj „Wróć do poprawy” niżej.</p> : null}
    </section>
  );
}
