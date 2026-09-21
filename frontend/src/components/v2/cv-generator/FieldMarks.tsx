/**
 * Oznaczenia pól generatora CV: co jest WYMAGANE do wygenerowania, a co można
 * pominąć. Jedno miejsce, żeby strona generatora i okno z profilu kandydata
 * mówiły tym samym językiem. O tym, CZY pole jest wymagane, decyduje wołający
 * — tą samą logiką, która włącza przycisk „Generuj".
 */
import { CheckCircle2 } from "lucide-react";

import { cn } from "@/lib/utils";

export const CHAMPION_HINT =
  "Champion (opcjonalnie) — z nim CV powstaje pod rekrutację, bez niego w trybie Redakcja.";

export function RequiredMark({ className }: { className?: string }) {
  return (
    <span
      className={cn("ml-1 text-xs font-normal text-destructive", className)}
      data-field-mark="required"
    >
      <span aria-hidden>*</span> wymagane
    </span>
  );
}

export function OptionalMark({ className }: { className?: string }) {
  return (
    <span
      className={cn("ml-1 text-xs font-normal text-muted-foreground", className)}
      data-field-mark="optional"
    >
      (opcjonalnie)
    </span>
  );
}

/** Legenda nad formularzem — pola bez oznaczenia mają wartość domyślną. */
export function FieldMarksLegend({ className }: { className?: string }) {
  return (
    <p className={cn("text-xs text-muted-foreground", className)}>
      <span className="text-destructive">* wymagane</span> — bez tego CV nie
      powstanie · (opcjonalnie) — można pominąć · pozostałe ustawienia mają
      wartość domyślną.
    </p>
  );
}

/**
 * Lista braków przy przycisku „Generuj". `missing` pochodzi z tej samej
 * logiki co `disabled` przycisku, więc „Wszystko gotowe" = przycisk aktywny.
 */
export function GenerationChecklist({
  missing,
  id,
  className,
}: {
  missing: readonly string[];
  id?: string;
  className?: string;
}) {
  if (missing.length === 0) {
    return (
      <p
        id={id}
        role="status"
        className={cn("flex items-center gap-1 text-xs font-medium text-success-muted-foreground", className)}
        data-testid="cvgen-checklist"
      >
        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
        Wszystko gotowe
      </p>
    );
  }
  return (
    <div
      id={id}
      role="status"
      className={cn("text-xs", className)}
      data-testid="cvgen-checklist"
    >
      <span className="font-medium text-destructive">Do wygenerowania CV brakuje:</span>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-foreground">
        {missing.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
