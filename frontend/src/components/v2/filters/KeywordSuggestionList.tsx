"use client";

import {
  formatSuggestionCount,
  GROUP_LABEL,
  type SuggestionOption,
} from "@/lib/keyword-suggest";
import { cn } from "@/lib/utils";

/**
 * Lista podpowiedzi pod polem słów kluczowych (`ChipField` z `suggest`).
 * Prezentacyjna: stan zaznaczenia i klawisze trzyma pole. Wybór idzie przez
 * `onMouseDown` + `preventDefault`, żeby pole nie straciło fokusu (blur
 * dodałby wpisany tekst jako osobne słowo, zanim klik doleci).
 */
export function KeywordSuggestionList({
  id,
  options,
  activeIndex,
  onPick,
  onHover,
  canSubmit,
}: {
  id: string;
  options: SuggestionOption[];
  activeIndex: number;
  onPick: (option: SuggestionOption) => void;
  onHover: (index: number) => void;
  canSubmit: boolean;
}) {
  return (
    <div className="absolute left-0 top-full z-50 mt-1 w-[min(26rem,calc(100vw-2rem))] overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-lg">
      <ul id={id} role="listbox" aria-label="Podpowiedzi" className="max-h-80 overflow-y-auto p-1">
        {options.map((option, index) => {
          const header = index === 0 || options[index - 1].group !== option.group;
          return (
            <li key={option.key} role="presentation">
              {header && (
                <div
                  role="presentation"
                  className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground"
                >
                  {GROUP_LABEL[option.group]}
                </div>
              )}
              <div
                id={`${id}-${index}`}
                role="option"
                aria-selected={index === activeIndex}
                onMouseDown={(e) => {
                  e.preventDefault();
                  onPick(option);
                }}
                onMouseEnter={() => onHover(index)}
                className={cn(
                  "flex min-h-9 cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm pointer-coarse:min-h-11",
                  index === activeIndex ? "bg-accent text-accent-foreground" : "",
                )}
              >
                <span className="min-w-0 flex-1 truncate">
                  {option.hit && <strong className="font-semibold">{option.hit}</strong>}
                  {option.rest}
                  {option.note && (
                    <span className="ml-1.5 text-xs text-muted-foreground">{option.note}</span>
                  )}
                </span>
                <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
                  {option.kindLabel}
                </span>
                <span className="w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {formatSuggestionCount(option.count)}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      <div className="hidden flex-wrap gap-x-3 gap-y-1 border-t border-border bg-muted/40 px-3 py-1.5 text-[11px] text-muted-foreground pointer-fine:flex">
        <span>
          <kbd className="font-semibold text-foreground">↑ ↓</kbd> wybierz
        </span>
        <span>
          <kbd className="font-semibold text-foreground">Enter</kbd> dodaj zaznaczone albo wpisane
        </span>
        <span>
          <kbd className="font-semibold text-foreground">,</kbd> dodaj jak wpisane
        </span>
        {canSubmit && (
          <span>
            <kbd className="font-semibold text-foreground">Enter</kbd> w pustym polu = Szukaj
          </span>
        )}
      </div>
    </div>
  );
}
