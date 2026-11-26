"use client";

import { ChevronDown, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { pluralPl } from "@/lib/contract-list-next";

export interface CollapsedSearchSummaryProps {
  /** Zdanie, jak serwer czyta słowa kluczowe (`describeKeywordSearch`). */
  sentence: string;
  /** Wartości z pigułek, których nie pokazują chipy pod paskiem (stawka, miasto, tryb). */
  parts: string[];
  /** Liczba pozostałych ustawionych filtrów. */
  moreCount: number;
  onExpand: () => void;
  onSearch?: () => void;
  pendingCount?: number;
  className?: string;
}

/**
 * Wyszukiwanie zwinięte do jednej linii (prośba rekrutera z 26.11.2026):
 * pole wymagań przy kilku wierszach z wariantami zajmowało przy 1280 × 720
 * cały ekran i tabela zaczynała się pod jego krawędzią.
 */
export function CollapsedSearchSummary({
  sentence,
  parts,
  moreCount,
  onExpand,
  onSearch,
  pendingCount = 0,
  className,
}: CollapsedSearchSummaryProps) {
  return (
    <section
      aria-label="Wyszukiwanie (zwinięte)"
      className={cn(
        "flex min-w-0 items-center gap-3 rounded-lg border border-border bg-card px-3 py-2 text-sm",
        className,
      )}
    >
      <button
        type="button"
        onClick={onExpand}
        aria-expanded={false}
        title={sentence}
        className="flex min-w-0 flex-1 items-center gap-3 rounded-md text-left focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="shrink-0 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Wyszukiwanie
        </span>
        <span className="min-w-0 flex-1 truncate text-foreground">{sentence}</span>
        {parts.map((part) => (
          <span
            key={part}
            className="hidden shrink-0 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary lg:inline"
          >
            {part}
          </span>
        ))}
        {moreCount > 0 && (
          <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
            +{moreCount} {pluralPl(moreCount, "filtr", "filtry", "filtrów")}
          </span>
        )}
      </button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onExpand}
        className="shrink-0 gap-1"
        data-tour="candidates.search-expand"
      >
        Pokaż filtry
        <ChevronDown className="h-3.5 w-3.5" aria-hidden />
      </Button>
      {onSearch && (
        <Button
          type="button"
          variant="primary"
          size="sm"
          onClick={onSearch}
          className={cn("shrink-0 gap-2", pendingCount > 0 && "ring-4 ring-primary/20")}
        >
          <Search className="h-4 w-4" aria-hidden />
          Szukaj{pendingCount > 0 ? ` (${pendingCount})` : ""}
        </Button>
      )}
    </section>
  );
}
