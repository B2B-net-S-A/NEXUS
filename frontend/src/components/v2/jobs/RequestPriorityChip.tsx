import { Badge } from "@/components/ui/badge";
import {
  PRIORITY_LEVEL_LABEL,
  PRIORITY_LEVEL_SHORT_LABEL,
  type PriorityLevel,
} from "@/lib/request-priority";
import { cn } from "@/lib/utils";

export interface RequestPriorityChipProps {
  /** Poziom z `priorityLevelOf(job)`; `null` / `undefined` nie renderuje nic. */
  level: PriorityLevel | null | undefined;
  /** Pełna etykieta („P1 Pilne”) zamiast krótkiej („P1”). */
  full?: boolean;
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
  size = "sm",
  className,
}: RequestPriorityChipProps) {
  if (level !== "p1" && level !== "accepting") return null;
  const label = PRIORITY_LEVEL_LABEL[level];
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
