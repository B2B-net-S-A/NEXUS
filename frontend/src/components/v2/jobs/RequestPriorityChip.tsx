import { Pause } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  PRIORITY_LEVEL_LABEL,
  PRIORITY_LEVEL_SHORT_LABEL,
  PRIORITY_PAUSED_HINT,
  type PriorityLevel,
} from "@/lib/request-priority";
import { cn } from "@/lib/utils";

export interface RequestPriorityChipProps {
  /** Poziom z `priorityLevelOf(job)`; `null` / `undefined` nie renderuje nic. */
  level: PriorityLevel | null | undefined;
  /** Pełna etykieta („P1 Pilne”) zamiast krótkiej („P1”). */
  full?: boolean;
  /**
   * P1 wstrzymany, bo mamy championa (`job.priority_paused`, D6): szara
   * plakietka z przerywaną ramką i pauzą. Dotyczy tylko P1.
   */
  paused?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/**
 * Plakietka priorytetu rekrutacji: „P1” w tonie alarmu, „Przyjmujemy”
 * przygaszone. P2 to stan domyślny i NIE ma plakietki — inaczej niosłaby ją
 * prawie każda rekrutacja i P1 przestałoby się wyróżniać.
 */
export function RequestPriorityChip({
  level,
  full = false,
  paused = false,
  size = "sm",
  className,
}: RequestPriorityChipProps) {
  if (level !== "p1" && level !== "accepting") return null;
  const label = PRIORITY_LEVEL_LABEL[level];
  if (level === "p1" && paused) {
    return (
      <Badge
        variant="outline"
        size={size}
        title={PRIORITY_PAUSED_HINT}
        data-priority={level}
        data-paused="true"
        className={cn("relative gap-0.5 border-dashed text-muted-foreground", className)}
      >
        <Pause className="h-2.5 w-2.5 shrink-0" aria-hidden="true" />
        <span aria-hidden="true">{full ? label : PRIORITY_LEVEL_SHORT_LABEL[level]}</span>
        <span className="sr-only">{PRIORITY_PAUSED_HINT}</span>
      </Badge>
    );
  }
  return (
    <Badge
      variant={level === "p1" ? "danger" : "outline"}
      size={size}
      title={label}
      data-priority={level}
      // `relative`: pełna nazwa dla czytników ekranu jest pozycjonowana
      // absolutnie i ma zostać w obrębie plakietki (przewijane tabele).
      className={cn(
        "relative",
        level === "accepting" && "text-muted-foreground",
        className,
      )}
    >
      {full ? (
        label
      ) : (
        <>
          <span aria-hidden="true">{PRIORITY_LEVEL_SHORT_LABEL[level]}</span>
          <span className="sr-only">{label}</span>
        </>
      )}
    </Badge>
  );
}
