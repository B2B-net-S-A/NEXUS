"use client";

import { cn } from "@/lib/utils";
import type { SearchTextInterpretation } from "@/lib/candidate-search-api";
import {
  summarizeTextInterpretation,
  type TextMode,
  type TextModeApplied,
} from "@/lib/candidate-search-semantics";

interface TextInterpretationLineProps {
  /** Co backend faktycznie zrobił z tekstem (`text_mode_applied`). */
  applied: TextModeApplied | null | undefined;
  interpretation: SearchTextInterpretation | null | undefined;
  /** Tryb wybrany przez rekrutera (`null`/`auto` = automatycznie). */
  textMode?: TextMode | null;
  /**
   * Przełącznik „Dosłownie / Po znaczeniu". Bez niego linia tylko informuje
   * (np. lista kandydatów zna wyłącznie dopasowanie dosłowne).
   */
  onTextModeChange?: (mode: TextMode) => void;
  /** Dopisek pod zdaniem, np. „Lista szuka tekstu dosłownie". */
  note?: string;
  className?: string;
}

const SWITCH: ReadonlyArray<readonly [Exclude<TextMode, "auto">, string]> = [
  ["literal", "Dosłownie"],
  ["semantic", "Po znaczeniu"],
];

/**
 * „Rozumiem to jako: osoba / słowa kluczowe / po znaczeniu" pod polem tekstu
 * (decyzja 21.09.2026). Automat backendu bywa w błędzie — przełącznik pozwala
 * wymusić tryb, a ponowne kliknięcie wybranego trybu wraca do automatu.
 */
export function TextInterpretationLine({
  applied,
  interpretation,
  textMode,
  onTextModeChange,
  note,
  className,
}: TextInterpretationLineProps) {
  const summary = summarizeTextInterpretation(applied, interpretation);
  if (!summary) return null;
  const manual = textMode === "literal" || textMode === "semantic";
  return (
    <div
      data-testid="text-interpretation"
      className={cn(
        "flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground",
        className,
      )}
    >
      <span role="status">
        Rozumiem to jako:{" "}
        <strong className="font-medium text-foreground">{summary.label}</strong>
        {summary.detail ? ` (${summary.detail})` : ""}
        {manual ? " — wybrane ręcznie" : ""}
      </span>
      {onTextModeChange && (
        <span
          role="group"
          aria-label="Jak szukać tekstu"
          className="inline-flex rounded-md border border-border p-0.5"
        >
          {SWITCH.map(([mode, label]) => {
            const active = textMode === mode;
            return (
              <button
                key={mode}
                type="button"
                aria-pressed={active}
                onClick={() => onTextModeChange(active ? "auto" : mode)}
                title={
                  active
                    ? "Kliknij ponownie, żeby wrócić do trybu automatycznego"
                    : undefined
                }
                className={cn(
                  "rounded px-2 py-0.5 transition-colors",
                  active
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted",
                )}
              >
                {label}
              </button>
            );
          })}
        </span>
      )}
      {manual && onTextModeChange && (
        <button
          type="button"
          onClick={() => onTextModeChange("auto")}
          className="underline-offset-2 hover:underline"
        >
          Automatycznie
        </button>
      )}
      {note && <span className="basis-full text-[11px]">{note}</span>}
    </div>
  );
}
