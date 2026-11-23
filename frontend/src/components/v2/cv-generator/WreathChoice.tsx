"use client";

import type { CvWreath } from "@/lib/api";

import { Segmented } from "./GeneratorParts";

const OPTIONS: { value: CvWreath; label: string; title: string }[] = [
  { value: "auto", label: "Automatycznie", title: "Certyfikat, gdy klient go wymaga (MUST), inaczej szkoła" },
  { value: "cert", label: "Certyfikat", title: "Najważniejszy certyfikat dla tej roli" },
  { value: "school", label: "Szkoła", title: "Najwyższy dyplom" },
];

export interface WreathChoiceProps {
  value: CvWreath;
  onChange: (value: CvWreath) => void;
  disabled?: boolean;
}

/**
 * Co stoi w wieńcu w „Edukacji” nowego CV (Artur 23.11.2026): wieniec przyciąga
 * wzrok, a dla części ról ważniejszy jest certyfikat niż uczelnia. Domyślnie
 * certyfikat z wymagań MUST klienta, inaczej szkoła; rekruter może to zmienić.
 */
export function WreathChoice({ value, onChange, disabled = false }: WreathChoiceProps) {
  return (
    <div className="grid gap-1.5" data-testid="cv-wreath-choice">
      <p className="text-sm font-semibold text-foreground">W wieńcu (Edukacja)</p>
      <Segmented<CvWreath> label="W wieńcu" value={value} onChange={onChange} disabled={disabled} options={OPTIONS} />
      <p className="text-xs leading-relaxed text-muted-foreground">
        Automatycznie: certyfikat, gdy klient go wymaga (MUST), inaczej szkoła. Reszta certyfikatów stoi obok z podpisem.
      </p>
    </div>
  );
}
