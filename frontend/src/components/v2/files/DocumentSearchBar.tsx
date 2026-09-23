"use client";

import { type KeyboardEvent, type RefObject } from "react";
import { ChevronDown, ChevronUp, Loader2, Search, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { isSearchableQuery } from "@/lib/document-text-search";

/** Czy da się szukać w bieżącym dokumencie. */
export type DocumentTextAvailability =
  | "pending" // dokument się ładuje / tekst jeszcze nie sprawdzony
  | "has_text"
  | "no_text"; // skan albo obraz — brak warstwy tekstu

export interface DocumentFindResult {
  current: number;
  total: number;
  pending: boolean;
}

export const EMPTY_FIND_RESULT: DocumentFindResult = {
  current: 0,
  total: 0,
  pending: false,
};

const SEARCH_ROOT_ATTR = "data-document-search";

/**
 * Esc w polu z wpisanym zapytaniem ma wyczyścić zapytanie, a NIE zamknąć okno
 * podglądu. Radix łapie Esc na `document` w fazie capture — zanim dotrze do
 * pola — więc `stopPropagation` w polu nie wystarcza. Podpinamy to pod
 * `onEscapeKeyDown` okna.
 */
export function keepDialogOpenOnDocumentSearchEscape(event: {
  target: EventTarget | null;
  preventDefault: () => void;
}): void {
  const target = event.target;
  if (
    target instanceof HTMLInputElement &&
    target.closest(`[${SEARCH_ROOT_ATTR}]`) &&
    target.value.length > 0
  ) {
    event.preventDefault();
  }
}

function statusText(
  query: string,
  availability: DocumentTextAvailability,
  result: DocumentFindResult,
): string | null {
  if (availability === "no_text") {
    return "Ten plik to skan — nie ma w nim tekstu do przeszukania";
  }
  if (!isSearchableQuery(query)) return null;
  if (availability === "pending" || result.pending) return "Szukam…";
  if (result.total === 0) return "Brak wyników";
  return `${result.current} z ${result.total}`;
}

export function DocumentSearchBar({
  query,
  onQueryChange,
  availability,
  result,
  onNext,
  onPrevious,
  inputRef,
  placeholder = "Szukaj w CV",
  className,
}: {
  query: string;
  onQueryChange: (query: string) => void;
  availability: DocumentTextAvailability;
  result: DocumentFindResult;
  onNext: () => void;
  onPrevious: () => void;
  inputRef: RefObject<HTMLInputElement | null>;
  placeholder?: string;
  className?: string;
}) {
  const status = statusText(query, availability, result);
  const canStep =
    availability === "has_text" && isSearchableQuery(query) && result.total > 0;
  const noText = availability === "no_text";

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      if (!canStep) return;
      if (event.shiftKey) onPrevious();
      else onNext();
      return;
    }
    if (event.key === "Escape") {
      if (query.length > 0) {
        event.stopPropagation();
        onQueryChange("");
      } else {
        inputRef.current?.blur();
      }
    }
    // Strzałki w polu przesuwają kursor w tekście — nie przełączają CV.
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.stopPropagation();
    }
  };

  return (
    <div
      {...{ [SEARCH_ROOT_ATTR]: "" }}
      role="search"
      className={cn("flex min-w-0 items-center gap-2", className)}
    >
      <div className="relative min-w-0 flex-1 sm:max-w-xs">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          ref={inputRef}
          type="search"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label={placeholder}
          aria-keyshortcuts="Control+F Meta+F"
          title={`${placeholder} (Ctrl+F)`}
          autoComplete="off"
          spellCheck={false}
          className="h-8 w-full rounded-md border border-border bg-card pl-8 pr-14 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20 [&::-webkit-search-cancel-button]:hidden"
        />
        {query.length > 0 ? (
          <button
            type="button"
            onClick={() => {
              onQueryChange("");
              inputRef.current?.focus();
            }}
            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 pointer-coarse:after:absolute pointer-coarse:after:-inset-2 text-muted-foreground hover:bg-primary/10 hover:text-foreground"
            aria-label="Wyczyść wyszukiwanie"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : (
          <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-border px-1 text-[10px] text-muted-foreground sm:inline">
            Ctrl F
          </kbd>
        )}
      </div>

      {status ? (
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 text-xs tabular-nums",
            noText || (result.total === 0 && status === "Brak wyników")
              ? "text-muted-foreground"
              : "text-foreground",
          )}
          aria-live="polite"
        >
          {status === "Szukam…" ? (
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          ) : null}
          {status}
        </span>
      ) : (
        <span className="sr-only" aria-live="polite" />
      )}

      {!noText ? (
        <div className="inline-flex shrink-0 items-center rounded-md border border-border">
          <button
            type="button"
            onClick={onPrevious}
            disabled={!canStep}
            className="rounded-l-md p-1 pointer-coarse:p-2.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Poprzednie trafienie"
            aria-keyshortcuts="Shift+Enter"
          >
            <ChevronUp className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onNext}
            disabled={!canStep}
            className="rounded-r-md border-l border-border p-1 pointer-coarse:p-2.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Następne trafienie"
            aria-keyshortcuts="Enter"
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        </div>
      ) : null}
    </div>
  );
}
