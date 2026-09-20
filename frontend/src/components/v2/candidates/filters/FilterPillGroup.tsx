"use client";

import { cn } from "@/lib/utils";

/** Dodaje albo zdejmuje wartość z listy (multi-select „pigułek"). */
export function toggleInList<T>(list: readonly T[], value: T): T[] {
  return list.includes(value)
    ? list.filter((x) => x !== value)
    : [...list, value];
}

// Semantyczne tony „pigułek" — subtelny tint, gdy nieaktywne; pełny kolor po
// zaznaczeniu. Używane tam, gdzie kolor niesie znaczenie (status, dyspozycyjność);
// reszta grup zostaje neutralna (indygo), żeby nie robić tęczy. Statyczne klasy.
export type PillTone = "neutral" | "emerald" | "amber" | "rose" | "sky";

const PILL_TONE_CLASSES: Record<PillTone, { on: string; off: string }> = {
  neutral: {
    on: "bg-primary text-primary-foreground border-primary",
    off: "bg-card text-foreground border-border hover:bg-accent",
  },
  emerald: {
    on: "bg-success text-success-foreground border-success",
    off: "bg-success-muted text-success-muted-foreground border-success/30 hover:bg-success-muted/70",
  },
  amber: {
    on: "bg-warning text-warning-foreground border-warning",
    off: "bg-warning-muted text-warning-muted-foreground border-warning/30 hover:bg-warning-muted/70",
  },
  rose: {
    on: "bg-destructive text-destructive-foreground border-destructive",
    off: "bg-destructive-muted text-destructive-muted-foreground border-destructive/30 hover:bg-destructive-muted/70",
  },
  sky: {
    on: "bg-info text-info-foreground border-info",
    off: "bg-info-muted text-info-muted-foreground border-info/30 hover:bg-info-muted/70",
  },
};

/** Grupa „pigułek" — multi-select bez zagnieżdżonego popovera, wszystkie opcje
 *  widoczne od razu. Czysto prezentacyjna: stan trzyma rodzic. */
export function PillGroup<V extends string>({
  label,
  options,
  value,
  onToggle,
  tones,
}: {
  label: string;
  options: ReadonlyArray<{ value: V; label: string }>;
  value: readonly string[];
  onToggle: (value: V) => void;
  tones?: Partial<Record<V, PillTone>>;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => {
          const active = value.includes(opt.value);
          const tone = PILL_TONE_CLASSES[tones?.[opt.value] ?? "neutral"];
          return (
            <button
              key={String(opt.value)}
              type="button"
              onClick={() => onToggle(opt.value)}
              aria-pressed={active}
              className={cn(
                "px-2.5 py-1 text-xs rounded-full border transition-colors",
                active ? tone.on : tone.off,
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
