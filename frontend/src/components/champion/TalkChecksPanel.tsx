"use client";

/**
 * „Rekruter sprawdza w rozmowie” — druga lista wymagań (wariant A, decyzja
 * Artura 13.10.2026). Doświadczenie opisane zdaniem, branża, certyfikaty,
 * regulacje i umiejętności miękkie, których nie znajdziemy w CV słowem. Nie
 * filtrują kandydatów: w formularzu screeningu są punktem „Sprawdź w
 * rozmowie” (Potwierdził / Nie ma / Nie wiem).
 *
 * Dane to sekcja 4 Profilu Championa (`experience`); język pracy ma własne
 * pole (`basics.language`) — panel tylko go pokazuje.
 */

import { useId } from "react";

import { ChampionExperienceFields } from "@/components/champion/ChampionExperienceFields";
import type { ChampionExperience } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface TalkChecksPanelProps {
  value: ChampionExperience;
  onChange: (next: ChampionExperience) => void;
  /** Język pracy z pola „Język pracy” — tylko do wglądu. */
  language?: string | null;
  disabled?: boolean;
  className?: string;
}

export function TalkChecksPanel({
  value,
  onChange,
  language,
  disabled = false,
  className,
}: TalkChecksPanelProps) {
  const titleId = useId();
  return (
    <section
      aria-labelledby={titleId}
      className={cn("flex flex-col gap-2 rounded-lg border border-border bg-muted/40 p-3", className)}
      data-testid="talk-checks"
    >
      <div className="flex flex-col gap-0.5">
        <h3 id={titleId} className="text-sm font-semibold text-foreground">
          Rekruter sprawdza w rozmowie
        </h3>
        <p className="text-xs text-muted-foreground">
          Czego nie znajdziemy w CV słowem. Nie filtruje kandydatów — w formularzu screeningu
          każda pozycja jest punktem „Sprawdź w rozmowie”.
        </p>
      </div>
      {language?.trim() ? (
        <p className="text-xs text-foreground" data-testid="talk-checks-language">
          <span className="text-muted-foreground">Język pracy: </span>
          <span className="font-medium">{language.trim()}</span>
          <span className="text-muted-foreground"> (pole „Język pracy”)</span>
        </p>
      ) : null}
      <ChampionExperienceFields
        value={value}
        onChange={onChange}
        disabled={disabled}
        showNotes={false}
      />
    </section>
  );
}
