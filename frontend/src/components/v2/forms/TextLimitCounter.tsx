import { cn } from "@/lib/utils";

/** Licznik pokazuje się od 80% limitu — wcześniej tylko zabiera miejsce. */
const SHOW_FROM = 0.8;

interface TextLimitCounterProps {
  /** Długość tekstu, który pójdzie na serwer (po `trim()`). */
  length: number;
  max: number;
  className?: string;
}

/**
 * „1650 / 2000 znaków”, a ponad limitem „… — skróć o N” na czerwono.
 * Pole z tym licznikiem nie ma `maxLength`: wklejka nie ucina się po cichu,
 * tylko przycisk wysyłki czeka, aż tekst się zmieści (15.10.2026).
 */
export function TextLimitCounter({ length, max, className }: TextLimitCounterProps) {
  if (length < Math.round(max * SHOW_FROM)) return null;
  const over = length - max;
  return (
    <span
      data-testid="text-limit-counter"
      className={cn(
        "text-[11px] tabular-nums",
        over > 0 ? "font-semibold text-destructive-muted-foreground" : "text-muted-foreground",
        className,
      )}
    >
      {length} / {max} znaków{over > 0 ? ` — skróć o ${over}` : ""}
    </span>
  );
}
