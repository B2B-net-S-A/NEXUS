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
  ariaLabel?: string;
  onSubmit?: () => void;
  onClear?: () => void;
  inputProps?: Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
    "type" | "value" | "onChange" | "placeholder"
  >;
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
  /** Controls rendered at the end of the primary toolbar row. */
  actions?: React.ReactNode;
  chips?: FilterBarChip[];
  resultCount?: number;
  resultLabel?: React.ReactNode;
  onClearAll?: () => void;
  variant?: "plain" | "surface" | "sticky";
  ariaLabel?: string;
  className?: string;
}

export function FilterBar({
  search,
  filters,
  actions,
  chips,
  resultCount,
  resultLabel,
  onClearAll,
  variant = "plain",
  ariaLabel = "Filtry wyników",
  className,
}: FilterBarProps) {
  const hasChips = Boolean(chips && chips.length > 0);
  const computedResultLabel =
    resultLabel ??
    (typeof resultCount === "number"
      ? `${resultCount} ${resultCountLabel(resultCount)}`
      : null);

  return (
    <section
      aria-label={ariaLabel}
      className={cn(
        "flex flex-col gap-3",
        variant === "surface" && "rounded-lg border border-border bg-card p-3",
        variant === "sticky" &&
          "sticky top-0 z-20 border-b border-border bg-background/95 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/80",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-3">
        {search ? (
          <div className="relative min-w-[12rem] flex-1 sm:max-w-sm">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <input
              {...search.inputProps}
              type="search"
              value={search.value}
              onChange={(event) => search.onChange(event.target.value)}
              onKeyDown={(event) => {
                search.inputProps?.onKeyDown?.(event);
                if (event.defaultPrevented || event.key !== "Enter") return;
                if (search.onSubmit) {
                  event.preventDefault();
                  search.onSubmit();
                }
              }}
              placeholder={search.placeholder ?? "Szukaj…"}
              aria-label={
                search.ariaLabel ??
                search.inputProps?.["aria-label"] ??
                search.placeholder ??
                "Szukaj"
              }
              className={cn(
                "h-9 w-full appearance-none rounded-md border border-input bg-background pl-9 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-0 [&::-webkit-search-cancel-button]:hidden",
                search.onClear && search.value ? "pr-9" : "pr-3",
                search.inputProps?.className,
              )}
            />
            {search.onClear && search.value ? (
              <button
                type="button"
                onClick={search.onClear}
                aria-label="Wyczyść wyszukiwanie"
                className="absolute right-2 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <X aria-hidden className="size-3.5" />
              </button>
            ) : null}
          </div>
        ) : null}

        {filters ? (
          <div className="flex flex-wrap items-center gap-2">{filters}</div>
        ) : null}

        {computedResultLabel ? (
          <span className="ml-auto text-sm tabular-nums text-muted-foreground">
            {computedResultLabel}
          </span>
        ) : null}

        {actions ? (
          <div className={cn("flex flex-wrap items-center gap-2", !computedResultLabel && "ml-auto")}>
            {actions}
          </div>
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
                className="inline-flex size-4 items-center justify-center rounded-full transition-colors hover:bg-accent hover:text-accent-foreground focus:outline-none focus:ring-2 focus:ring-ring"
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
    </section>
  );
}

export function resultCountLabel(count: number): string {
  if (count === 1) return "wynik";
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
    return "wyniki";
  }
  return "wyników";
}
