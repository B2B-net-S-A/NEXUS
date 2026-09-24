"use client";

import {
  languageOptionEnabled,
  type CvLanguageChoice,
  type LanguagePolicy,
} from "./cv-generator-form";
import { Segmented } from "./GeneratorParts";

export interface LanguageChoiceProps {
  value: CvLanguageChoice;
  onChange: (value: CvLanguageChoice) => void;
  policy: LanguagePolicy;
  clientName: string | null;
  disabled?: boolean;
}

/** Język CV: PL · EN · Obie. Język wymuszony regułą klienta blokuje resztę. */
export function LanguageChoice({ value, onChange, policy, clientName, disabled = false }: LanguageChoiceProps) {
  const hint = policy.forced
    ? `${clientName ?? "Ten klient"} wymaga CV wyłącznie po ${policy.forced === "en" ? "angielsku" : "polsku"}.`
    : [
        clientName ? `Domyślnie z reguły klienta ${clientName}.` : null,
        "„Obie” robi dwa dokumenty jednym kliknięciem.",
      ].filter(Boolean).join(" ");
  const option = (v: CvLanguageChoice, label: string) => ({
    value: v,
    label,
    disabled: !languageOptionEnabled(v, policy),
    title: languageOptionEnabled(v, policy) ? undefined : "Klient wymaga innego języka",
  });
  return (
    <div className="grid gap-2 sm:grid-cols-[110px_minmax(0,1fr)] sm:items-start">
      <p className="pt-1.5 text-sm font-semibold text-foreground">Język</p>
      <div className="space-y-2">
        <Segmented<CvLanguageChoice>
          label="Język CV"
          value={value}
          onChange={onChange}
          disabled={disabled}
          options={[option("pl", "PL"), option("en", "EN"), option("both", "Obie")]}
        />
        <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      </div>
    </div>
  );
}
