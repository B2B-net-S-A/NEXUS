"use client";

/**
 * „Krytyczne (0–3)” — wybór umiejętności, które UKRYWAJĄ kandydatów
 * (decyzja Artura 30.09.2026). Reguły i zdania: `lib/critical-skills.ts`.
 *
 * Wybiera się wyłącznie spośród pozycji „Musi mieć”; pozycja, która nie jest
 * nazwą technologii ani narzędzia (branża, język, zdanie), jest wyszarzona —
 * serwer i tak by ją odrzucił. Nazwa spoza słownika jest dozwolona (08.10.2026).
 * Podpowiedź z historii i „Brak krytycznych” to dwa świadome wyjścia — pole
 * nigdy nie zgaduje za Delivery Leada.
 */

import { useId } from "react";
import { Loader2, Star } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  CRITICAL_MAX,
  CRITICAL_SUGGESTION_MAX,
  criticalStatusLine,
  includesLabel,
  normalizeMust,
  statSentence,
  suggestionButtonLabel,
  toggleCritical,
  type CriticalSuggestionState,
  type CriticalValue,
} from "@/lib/critical-skills";
import { apiErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";

export const CRITICAL_NOT_TECH_HINT =
  "To nie jest nazwa technologii ani narzędzia — nie może ukrywać kandydatów";
const CRITICAL_FULL_HINT = `Najwyżej ${CRITICAL_MAX} umiejętności krytyczne — najpierw odznacz jedną`;

export interface CriticalSkillsFieldProps {
  must: readonly string[];
  value: CriticalValue;
  onChange: (next: CriticalValue) => void;
  suggestion: CriticalSuggestionState;
  disabled?: boolean;
  /** `/jobs/new`: brak decyzji blokuje „Przekaż do searchu”. */
  missing?: boolean;
  className?: string;
}

export function CriticalSkillsField({
  must,
  value,
  onChange,
  suggestion,
  disabled = false,
  missing = false,
  className,
}: CriticalSkillsFieldProps) {
  const labelId = useId();
  const items = normalizeMust(must);
  const selected = value ?? [];
  const stale = selected.filter((item) => !includesLabel(items, item));
  const eligible = suggestion.eligible;
  const suggested = suggestion.data?.suggested ?? [];
  const stats = suggestion.data?.stats ?? {};
  const blockedReasons = suggestion.data?.blocked ?? {};
  const isNone = value != null && value.length === 0;
  const suggestionApplied =
    suggested.length > 0 &&
    selected.length === suggested.length &&
    suggested.every((item) => includesLabel(selected, item));
  const anyNotTech = eligible != null && items.some((item) => !includesLabel(eligible, item));
  const full = selected.length >= CRITICAL_MAX;

  return (
    <div
      className={cn(
        "space-y-2 rounded-lg border p-3",
        missing ? "border-warning ring-2 ring-warning-muted" : "border-border",
        className,
      )}
      role="group"
      aria-labelledby={labelId}
      data-testid="critical-skills-field"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span id={labelId} className="text-sm font-medium text-foreground">
          Krytyczne (0–{CRITICAL_MAX})
        </span>
        <span className="text-xs text-muted-foreground">wybierz z „Musi mieć”</span>
      </div>
      <p className="text-xs text-muted-foreground">
        Kandydat bez umiejętności krytycznej nie pojawi się na listach AI. Pozostałe MUST i NICE
        dają punkty.
      </p>

      {suggestion.emptyMust ? (
        <p className="text-xs text-muted-foreground" data-testid="critical-empty-must">
          Najpierw dodaj pozycje do „Musi mieć”.
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1.5" aria-label="Pozycje „Musi mieć”">
          {items.map((item) => {
            const on = includesLabel(selected, item);
            const notTech = eligible != null && !includesLabel(eligible, item);
            const blocked = !on && (notTech || full);
            const hint = notTech
              ? blockedReasons[item] || CRITICAL_NOT_TECH_HINT
              : !on && full
                ? CRITICAL_FULL_HINT
                : undefined;
            const stat = statSentence(stats[item]);
            return (
              <li key={item}>
                <button
                  type="button"
                  aria-pressed={on}
                  aria-disabled={disabled || blocked || undefined}
                  title={hint ?? stat ?? undefined}
                  onClick={() => {
                    if (disabled || blocked) return;
                    onChange(toggleCritical(value, item));
                  }}
                  className={cn(
                    "inline-flex h-7 items-center gap-1 rounded-full border px-2.5 text-xs font-medium transition-colors",
                    on
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-card text-foreground hover:bg-muted",
                    (blocked || disabled) && "cursor-not-allowed opacity-50 hover:bg-card",
                    notTech && "border-dashed",
                  )}
                  data-testid="critical-chip"
                >
                  {on ? <Star className="h-3 w-3 fill-current" aria-hidden /> : null}
                  {item}
                  {on ? <span className="sr-only"> — krytyczna</span> : null}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {anyNotTech ? (
        <p className="text-[11px] text-muted-foreground">
          Przerywana ramka: {CRITICAL_NOT_TECH_HINT.charAt(0).toLowerCase()}
          {CRITICAL_NOT_TECH_HINT.slice(1)}.
        </p>
      ) : null}
      {stale.length > 0 ? (
        <p className="text-xs text-warning-muted-foreground" data-testid="critical-stale">
          {stale.map((s) => `„${s}”`).join(", ")} nie ma już w „Musi mieć” — przy zapisie
          zniknie z krytycznych.
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {suggested.length > 0 && !suggestionApplied ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => onChange(suggested.slice(0, CRITICAL_SUGGESTION_MAX))}
            data-testid="critical-use-suggestion"
          >
            {suggestionButtonLabel(suggested)}
          </Button>
        ) : null}
        <Button
          type="button"
          size="sm"
          variant={isNone ? "secondary" : "ghost"}
          aria-pressed={isNone}
          disabled={disabled}
          onClick={() => onChange(isNone ? null : [])}
          data-testid="critical-none"
        >
          Brak krytycznych
        </Button>
        {suggestion.isLoading && !suggestion.emptyMust ? (
          <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" aria-hidden />
        ) : null}
      </div>
      {suggested.length > 0 && !suggestionApplied ? (
        <ul className="space-y-0.5 text-[11px] text-muted-foreground" data-testid="critical-suggestion-stats">
          {suggested.map((item) => {
            const sentence = statSentence(stats[item]);
            return sentence ? (
              <li key={item}>
                {item}: {sentence}
              </li>
            ) : null;
          })}
        </ul>
      ) : null}

      {suggestion.isError ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 rounded-md bg-destructive/10 px-2 py-1.5 text-xs text-destructive"
          data-testid="critical-suggestion-error"
        >
          <span>
            {apiErrorMessage(suggestion.error, "Nie udało się pobrać podpowiedzi z historii.")}
          </span>
          <Button type="button" size="sm" variant="ghost" onClick={suggestion.retry}>
            Ponów
          </Button>
        </div>
      ) : null}

      <p
        className={cn(
          "text-xs",
          value == null ? "text-warning-muted-foreground" : "text-muted-foreground",
        )}
        aria-live="polite"
        data-testid="critical-status"
      >
        {suggestion.isError && value == null
          ? "Nie zdecydowano — nie wiemy, co podpowiada historia (spróbuj ponownie)"
          : value == null && suggestion.isLoading && !suggestion.emptyMust
            ? "Nie zdecydowano — sprawdzam podpowiedź z historii…"
            : criticalStatusLine(value, suggested)}
      </p>
    </div>
  );
}
