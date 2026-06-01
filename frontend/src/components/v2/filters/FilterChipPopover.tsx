"use client";

import type { ReactNode } from "react";
import { ChevronDown, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface FilterChipPopoverProps {
  /** Label shown when no filter value is active (e.g. "Lokalizacja"). */
  label: string;
  /** Active value summary shown next to the label when filter is non-empty.
   *  Pass null/undefined when no value is set. */
  activeLabel?: string | null;
  /** Number of selected values – drives the count badge for multi-selects.
   *  Omit / set to 0 to hide the badge. */
  activeCount?: number;
  /** Click handler for the × clear button. Only shown when activeLabel is
   *  set. Should reset the underlying filter state to empty. */
  onClear?: () => void;
  /** Width hint for the popover content (e.g. "w-72"). Defaults to w-80. */
  contentWidthClass?: string;
  /** Popover body – the actual filter input/selector. */
  children: ReactNode;
}

/** Chip-style trigger button + popover for a single filter on the main
 *  toolbar (Phase 2 – Traffit parity).
 *
 *  Lifts individual filter components (LocationInput, CompanyAutocomplete,
 *  TalentPoolMultiSelect, …) out of the giant "Filtry zaawansowane" popup
 *  into always-visible chip buttons. When the filter has a value, the chip
 *  shows it inline and gets a × clear button – exactly Traffit's pattern.
 *
 *  This is a presentational wrapper – wiring (value, onChange) lives on the
 *  child component the caller passes in. */
export function FilterChipPopover({
  label,
  activeLabel,
  activeCount,
  onClear,
  contentWidthClass = "w-80",
  children,
}: FilterChipPopoverProps) {
  const isActive = Boolean(activeLabel);
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="sm"
          variant={isActive ? "primary" : "outline"}
          className={cn(
            "gap-1.5 shadow-sm",
            !isActive &&
              "bg-card hover:bg-violet-50 hover:border-violet-300 dark:hover:bg-violet-950/30 dark:hover:border-violet-700",
            isActive && "pr-1.5",
          )}
        >
          <span className="truncate max-w-[180px]">
            {isActive ? `${label}: ${activeLabel}` : label}
          </span>
          {activeCount && activeCount > 1 ? (
            <Badge variant="burgundy" size="sm" className="-mr-0.5">
              {activeCount}
            </Badge>
          ) : null}
          {isActive && onClear ? (
            <span
              role="button"
              aria-label={`Wyczyść ${label.toLowerCase()}`}
              onClick={(e) => {
                e.stopPropagation();
                onClear();
              }}
              className="inline-flex items-center justify-center h-5 w-5 rounded-full hover:bg-white/20"
            >
              <X className="h-3 w-3" />
            </span>
          ) : (
            <ChevronDown className="h-3 w-3 opacity-60" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className={cn("p-3", contentWidthClass)}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
