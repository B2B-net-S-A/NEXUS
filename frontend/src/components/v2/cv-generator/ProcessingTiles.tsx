"use client";

import type { CvProcessingMode } from "./cv-generator-form";
import { Segmented } from "./GeneratorParts";

export interface ProcessingTilesProps {
  value: CvProcessingMode;
  onChange: (value: CvProcessingMode) => void;
  hasChampion: boolean;
  /** Sufit klienta „Przepisanie” — kafle nieaktywne, powstaje CV bez redakcji. */
  capBasic?: boolean;
  disabled?: boolean;
}

/** Dwa kafle obróbki: Redakcja i Pod rekrutację. Domyślny wynika z Championa. */
export function ProcessingTiles({ value, onChange, hasChampion, capBasic = false, disabled = false }: ProcessingTilesProps) {
  const hint = capBasic
    ? "Ten klient przyjmuje wyłącznie przepisanie faktów z CV — bez redakcji i bez dopasowania do rekrutacji."
    : value === "tailored"
      ? hasChampion
        ? "Jest Champion, więc dopasujemy CV do wymagań tej rekrutacji: kolejność doświadczeń i pogrubione technologie MUST."
        : "Bez Championa „Pod rekrutację” nie zadziała — powstanie Redakcja. Wgraj Championa wyżej."
      : hasChampion
        ? "Te same fakty, poprawiony język. Bez dopasowania do wymagań rekrutacji."
        : "Bez Championa robimy Redakcję. Wgraj Championa wyżej, a przełączymy na „Pod rekrutację”.";
  return (
    <div className="grid gap-2 sm:grid-cols-[110px_minmax(0,1fr)] sm:items-start">
      <p className="pt-1.5 text-sm font-semibold text-foreground">Obróbka</p>
      <div className="space-y-2">
        <Segmented<CvProcessingMode>
          label="Obróbka treści"
          value={value}
          onChange={onChange}
          disabled={disabled || capBasic}
          options={[
            { value: "polished", label: "Redakcja" },
            { value: "tailored", label: "Pod rekrutację" },
          ]}
        />
        <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      </div>
    </div>
  );
}
