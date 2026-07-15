"use client";

import * as React from "react";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export interface FilterBarSearch {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

export interface FilterBarChip {
  id: string;
  label: string;
  onRemove: () => void;
}

export interface FilterBarProps {
  search?: FilterBarSearch;
  /** Slot for Popover-based filter controls supplied by the caller. */
  filters?: React.ReactNode;
  chips?: FilterBarChip[];
  resultCount?: number;
  onClearAll?: () => void;
  className?: string;
}

export function FilterBar({
  search,
  filters,
  chips,
  resultCount,
  onClearAll,
  className,
}: FilterBarProps) {
  const hasChips = Boolean(chips && chips.length > 0);

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex flex-wrap items-center gap-3">
        {search ? (
          <div className="relative min-w-[12rem] flex-1 sm:max-w-xs">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="text"
              value={search.value}
              onChange={(event) => search.onChange(event.target.value)}
              placeholder={search.placeholder ?? "Szukaj…"}
              className="h-9 w-full rounded-md border border-input bg-background pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-0"
            />
          </div>
        ) : null}

        {filters ? (
          <div className="flex flex-wrap items-center gap-2">{filters}</div>
        ) : null}

        {typeof resultCount === "number" ? (
          <span className="ml-auto text-sm tabular-nums text-muted-foreground">
            {resultCount} {resultLabel(resultCount)}
          </span>
        ) : null}
      </div>

      {hasChips ? (
        <div className="flex flex-wrap items-center gap-2">
          {chips!.map((chip) => (
            <Badge
              key={chip.id}
              variant="soft"
              className="gap-1 pr-1"
            >
              <span className="truncate">{chip.label}</span>
              <button
                type="button"
                onClick={chip.onRemove}
                aria-label={`Usuń filtr: ${chip.label}`}
                className="inline-flex size-4 items-center justify-center rounded-full transition-colors hover:bg-primary/20 focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <X aria-hidden className="size-3" />
              </button>
            </Badge>
          ))}

          {onClearAll ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onClearAll}
            >
              Wyczyść wszystko
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function resultLabel(count: number): string {
  if (count === 1) return "wynik";
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
    return "wyniki";
  }
  return "wyników";
}
