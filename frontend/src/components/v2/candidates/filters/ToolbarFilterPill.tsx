"use client";

import type { ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

interface ToolbarFilterPillProps {
  label: string;
  /** Liczba aktywnych wartości w tej grupie filtrów. */
  count: number;
  icon?: ReactNode;
  children: ReactNode;
  contentClassName?: string;
}

/**
 * Pigułka filtra w pasku nad listą kandydatów — skrót do jednej grupy z
 * szuflady „Filtry" bez otwierania całej szuflady. Liczba przy etykiecie mówi,
 * ile wartości tej grupy jest aktywnych.
 */
export function ToolbarFilterPill({
  label,
  count,
  icon,
  children,
  contentClassName,
}: ToolbarFilterPillProps) {
  const active = count > 0;
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          className={cn(
            "h-9 gap-1.5 rounded-full bg-card shadow-xs",
            active && "border-primary bg-primary/10 text-primary font-semibold",
          )}
          aria-label={active ? `${label} (aktywne: ${count})` : label}
        >
          {icon}
          {label}
          {active ? (
            <Badge variant="burgundy" size="sm" className="-mr-0.5">
              {count}
            </Badge>
          ) : (
            <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden="true" />
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className={cn("w-80 space-y-3 p-3", contentClassName)}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
