"use client";

import { Lock } from "lucide-react";

import type { CvLayout } from "@/lib/api";

import { Segmented } from "./GeneratorParts";

/** Etykiety układu CV wspólne dla generatora, karty i edytora (22.11.2026). */
export const CV_LAYOUT_LABEL: Record<CvLayout, string> = {
  new: "Nowe CV",
  classic: "Klasyczne (Word)",
};

/** Krótki opis układu do faktów karty: „Nowe CV · PDF”. */
export function cvLayoutFact(layout: CvLayout): string {
  return layout === "new" ? "Nowe CV · PDF" : "Klasyczne · Word";
}

const OPTIONS = [
  { value: "new" as const, label: CV_LAYOUT_LABEL.new },
  { value: "classic" as const, label: CV_LAYOUT_LABEL.classic },
];
// Wąska karta (ok. 250 px obok miniatury): krótsze etykiety, pełne w podpowiedzi.
const COMPACT_OPTIONS = [
  { value: "new" as const, label: "Nowe CV", title: "Nowe CV — PDF" },
  { value: "classic" as const, label: "Klasyczne", title: "Klasyczne — szablon Word" },
];

export interface LayoutChoiceProps {
  value: CvLayout;
  onChange: (value: CvLayout) => void;
  /** Gdzie stoi przełącznik: generator (przed „Generuj”) albo karta gotowego CV. */
  place: "generator" | "card";
  clientName?: string | null;
  /** Domyślny układ klienta — podpowiedź w generatorze. */
  clientDefault?: CvLayout;
  disabled?: boolean;
  /** CV jest już u klienta: przełącznik zablokowany (jak podmiana CV). */
  lockedAfterSend?: boolean;
  /** Etykieta nad przełącznikiem — wąska karta „CV do klienta”. */
  compact?: boolean;
}

/**
 * Układ CV: Nowe CV (PDF) albo Klasyczne (Word). Jedno ustawienie CV —
 * ten sam tekst w obu układach, przełączenie nie generuje CV od nowa.
 */
export function LayoutChoice({
  value,
  onChange,
  place,
  clientName = null,
  clientDefault = "classic",
  disabled = false,
  lockedAfterSend = false,
  compact = false,
}: LayoutChoiceProps) {
  const hint =
    place === "generator"
      ? [
          clientDefault === "new" && clientName
            ? `${clientName}: domyślnie Nowe CV.`
            : null,
          "Układ zmienisz też po wygenerowaniu — bez generowania od nowa.",
        ]
          .filter(Boolean)
          .join(" ")
      : "Ten sam tekst w obu układach. Zmiana układu nie generuje CV od nowa i nie kasuje poprawek.";
  return (
    <div
      data-testid={`cv-layout-choice-${place}`}
      className={compact ? "grid gap-2" : "grid gap-2 sm:grid-cols-[110px_minmax(0,1fr)] sm:items-start"}
    >
      <p className="pt-1.5 text-sm font-semibold text-foreground">Układ CV</p>
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented<CvLayout>
            label="Układ CV"
            value={value}
            onChange={onChange}
            disabled={disabled || lockedAfterSend}
            options={compact ? COMPACT_OPTIONS : OPTIONS}
          />
          {lockedAfterSend ? (
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Lock className="h-3.5 w-3.5" aria-hidden /> po wysyłce do klienta
            </span>
          ) : null}
        </div>
        {lockedAfterSend ? null : (
          <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
        )}
      </div>
    </div>
  );
}
