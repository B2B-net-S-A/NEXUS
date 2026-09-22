"use client";

import { AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SearchTextInterpretation } from "@/lib/candidate-search-api";
import type { TextModeFilter } from "@/lib/url-filters";

export type ListTextModeApplied = "literal" | "semantic" | "keywords" | "none";

export interface ListSearchInterpretationProps {
  /** Co backend faktycznie zrobił z tekstem. */
  applied: ListTextModeApplied | null | undefined;
  interpretation?: SearchTextInterpretation | null;
  /** Wyszukiwanie po znaczeniu chwilowo niedostępne — pokazaliśmy dosłowne. */
  degraded?: boolean;
  /** Pula wyników po znaczeniu jest przycięta. */
  capReached?: boolean;
  textMode: TextModeFilter;
  onTextModeChange: (mode: TextModeFilter) => void;
  className?: string;
}

const PERSON_KINDS = new Set(["name", "email", "phone"]);

/**
 * Jedno zdanie pod polem wyszukiwania listy: jak odczytaliśmy tekst i jak to
 * zmienić. Tekst wyglądający na osobę (nazwisko, e-mail, telefon) zawsze
 * szukamy dosłownie — przełącznik „po znaczeniu" nie ma tam sensu.
 */
export function ListSearchInterpretation({
  applied,
  interpretation,
  degraded = false,
  capReached = false,
  textMode,
  onTextModeChange,
  className,
}: ListSearchInterpretationProps) {
  if (!applied || applied === "none") return null;
  const manual = textMode !== "auto";
  const personLike = interpretation ? PERSON_KINDS.has(interpretation.kind) : false;
  const linkClass = "font-medium text-primary underline-offset-2 hover:underline";

  return (
    <div
      data-testid="list-search-interpretation"
      className={cn("flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground", className)}
    >
      {degraded ? (
        <span role="status" className="inline-flex items-center gap-1 text-warning-muted-foreground">
          <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
          Wyszukiwanie po znaczeniu chwilowo niedostępne — pokazujemy dopasowania dosłowne.
        </span>
      ) : applied === "semantic" ? (
        <>
          <span role="status">Szukamy po znaczeniu — podobne profile też się liczą.</span>
          <button type="button" className={linkClass} onClick={() => onTextModeChange("literal")}>
            Szukaj dosłownie
          </button>
        </>
      ) : (
        <>
          <span role="status">Szukamy dosłownie (nazwisko, e-mail, telefon lub fraza).</span>
          {!personLike && (
            <button type="button" className={linkClass} onClick={() => onTextModeChange("semantic")}>
              Szukaj po znaczeniu
            </button>
          )}
        </>
      )}
      {manual && (
        <button type="button" className={linkClass} onClick={() => onTextModeChange("auto")}>
          Automatycznie
        </button>
      )}
      {capReached && !degraded && (
        <span className="basis-full">Pokazujemy najtrafniejsze wyniki (pula ograniczona).</span>
      )}
    </div>
  );
}
