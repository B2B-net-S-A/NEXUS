"use client";

import { useEffect, useState } from "react";
import { Check, Palette } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { THEME_PALETTES, useThemeStore } from "@/store/theme";

/**
 * Quick color-theme picker in the topbar. Lets each user choose a palette
 * (accent + chrome + sidebar). Persisted per-browser via the theme store.
 */
export function PaletteSwitcher() {
  const palette = useThemeStore((s) => s.palette);
  const setPalette = useThemeStore((s) => s.setPalette);
  const [mounted, setMounted] = useState(false);

  // Palette is read from localStorage on the client only — avoid hydration mismatch.
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="h-8 w-8" aria-hidden />;
  }

  const active = THEME_PALETTES.find((p) => p.id === palette) ?? THEME_PALETTES[0];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          aria-label="Wybierz motyw koloru"
          title={`Motyw koloru: ${active.label}`}
          className="h-8 w-8 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <Palette className="h-4 w-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuLabel>Motyw koloru</DropdownMenuLabel>
        {THEME_PALETTES.map((p) => {
          const isActive = p.id === palette;
          return (
            <DropdownMenuItem
              key={p.id}
              onSelect={() => setPalette(p.id)}
              className="cursor-pointer gap-2.5"
            >
              <span
                className={cn(
                  "h-4 w-4 shrink-0 rounded-full border border-black/10 dark:border-white/15",
                  isActive && "ring-2 ring-offset-1 ring-offset-popover ring-foreground/30"
                )}
                style={{ backgroundColor: p.swatch }}
                aria-hidden
              />
              <span className="flex-1">{p.label}</span>
              {isActive && <Check className="h-4 w-4 shrink-0 text-foreground" />}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
