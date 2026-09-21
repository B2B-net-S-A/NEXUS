"use client";

/**
 * Podpowiedzi „Z notatek: … — Użyj" pod polami stawki na stanowisku screeningu.
 *
 * Kliknięcie wyłącznie WYPEŁNIA pole (jak wpisanie z klawiatury): stawka idzie
 * do serwera dopiero przy ruchu na „Zweryfikowany", a dostępność — przy
 * zwykłym „Zapisz screening". Bez `rate` (w tym przy `rate_redacted`) chip
 * stawki nie istnieje: rola bez wglądu w stawki nie widzi nawet śladu kwoty.
 */

import { StickyNote } from "lucide-react";

import {
  availabilitySuggestionText,
  notedAtLabel,
  rateSuggestionFill,
  rateSuggestionLabel,
  type ScreeningSuggestions,
} from "@/lib/screening-suggestions";
import type { RateUnit } from "@/lib/api";

export interface ScreeningSuggestionChipsProps {
  suggestions: ScreeningSuggestions | null | undefined;
  disabled?: boolean;
  onUseRate: (fill: { rate: string; unit: RateUnit }) => void;
  /** Brak = arkusz nie ma pola, do którego dałoby się wpisać dostępność. */
  onUseAvailability?: (text: string) => void;
}

function Chip({
  text,
  actionLabel,
  onUse,
  hint,
}: {
  text: string;
  actionLabel: string;
  onUse?: () => void;
  hint?: string;
}) {
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground">
      <StickyNote className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span className="min-w-0 truncate" title={text}>
        Z notatek: <span className="font-medium text-foreground">{text}</span>
      </span>
      {onUse ? (
        <button
          type="button"
          onClick={onUse}
          aria-label={actionLabel}
          className="shrink-0 font-semibold text-primary hover:underline"
        >
          Użyj
        </button>
      ) : hint ? (
        <span className="shrink-0 italic">{hint}</span>
      ) : null}
    </span>
  );
}

export function ScreeningSuggestionChips({
  suggestions,
  disabled = false,
  onUseRate,
  onUseAvailability,
}: ScreeningSuggestionChipsProps) {
  const rate = suggestions?.rate_redacted ? undefined : suggestions?.rate;
  const availabilityText = suggestions?.availability
    ? availabilitySuggestionText(suggestions.availability)
    : null;
  if (!rate && !availabilityText) return null;

  const fill = rate ? rateSuggestionFill(rate) : null;
  const availabilityNoted = notedAtLabel(suggestions?.availability?.noted_at);
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="screening-suggestions">
      {rate ? (
        <Chip
          text={rateSuggestionLabel(rate)}
          actionLabel="Użyj stawki z notatek"
          onUse={!disabled && fill ? () => onUseRate(fill) : undefined}
          hint={!fill ? "inna waluta lub jednostka — wpisz ręcznie" : undefined}
        />
      ) : null}
      {availabilityText ? (
        <Chip
          text={availabilityNoted ? `${availabilityText} · ${availabilityNoted}` : availabilityText}
          actionLabel="Dopisz dostępność z notatek do notatek rekrutera"
          onUse={
            !disabled && onUseAvailability
              ? () => onUseAvailability(availabilityText)
              : undefined
          }
        />
      ) : null}
    </div>
  );
}
