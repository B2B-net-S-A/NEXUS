"use client";

import { CheckCircle2, Upload, UserSearch } from "lucide-react";
import { cn } from "@/lib/utils";

export type CvSourceMode = "new" | "old";

/** `label` to dostępna nazwa przycisku (czytają ją testy generatora). */
const CV_SOURCE_TILES = [
  {
    mode: "new",
    label: "Z procesu w NEXUSie",
    title: "Z procesu w NEXUSie",
    description: "Kandydat jest w rekrutacji — CV i notatki bierzemy z procesu.",
    icon: UserSearch,
  },
  {
    mode: "old",
    label: "Mam tylko plik CV (bez procesu)",
    title: "Mam tylko plik CV",
    description: "Wgraj PDF albo DOCX — bez kandydata w procesie.",
    icon: Upload,
  },
] as const;

/**
 * Wybór źródła CV w generatorze: dwa równorzędne kafelki. Do 09.2026 upload
 * był dyskretnym linkiem w prawym rogu i zespół go nie zauważał — szukał
 * kandydata w procesie, choć miał w ręku sam plik.
 */
export function CvSourceTiles({
  value,
  onChange,
  className,
}: {
  value: CvSourceMode;
  onChange: (mode: CvSourceMode) => void;
  className?: string;
}) {
  return (
    <div role="group" aria-label="Źródło CV" className={cn("grid gap-3 sm:grid-cols-2", className)}>
      {CV_SOURCE_TILES.map((tile) => {
        const selected = value === tile.mode;
        const Icon = tile.icon;
        return (
          <button
            key={tile.mode}
            type="button"
            aria-label={tile.label}
            aria-pressed={selected}
            onClick={() => {
              if (!selected) onChange(tile.mode);
            }}
            className={cn(
              "flex items-start gap-3 rounded-xl border-2 p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              selected
                ? "border-primary bg-primary/5"
                : "border-border bg-card hover:border-primary/40 hover:bg-muted/30",
            )}
          >
            <span
              className={cn(
                "rounded-lg p-2",
                selected ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
              )}
            >
              <Icon className="h-5 w-5" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 font-semibold text-foreground">
                {tile.title}
                {selected && <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />}
              </span>
              <span className="mt-0.5 block text-sm text-muted-foreground">{tile.description}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}
