"use client";

import { useEffect, useState } from "react";
import { Bot, Check, ChevronRight, Gamepad2, Moon, Palette, X } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useJarvisMascotVisibility } from "@/components/jarvis/useJarvisMascotVisibility";
import { activeSeason, companyDate } from "@/lib/worlds/seasons";
import { THEME_WORLDS, useThemeStore, worldScheme } from "@/store/theme";

import { PaletteMenuItems } from "./PaletteSwitcher";
import { useKidsModeToggle } from "./ThemeControls";
import { openWorldGallery } from "./WorldGallery";

/**
 * „Wygląd” w górnym pasku: świat, motyw koloru i tryb ciemny w jednym menu
 * (decyzja Artura 13.10.2026; światy od 13.11.2026 — `docs/claude/ui/swiaty-wygladu.md`).
 * Trzy osobne przyciski po 32 px zabierały 112 px — to miejsce zajmuje
 * przycisk Ligi Mistrzów. Przy włączonym świecie menu chowa motyw koloru
 * i tryb ciemny, bo świat ma własne kolory i sam wybiera jasny albo ciemny.
 * Na telefonie przełączniki zostają osobno w szufladzie nawigacji.
 * „Robot Jarvisa w rogu” — tu się go przywraca po „Schowaj” na samym robocie.
 */
export function AppearanceMenu() {
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const { kidsMode, toggle: toggleKidsMode } = useKidsModeToggle();
  const mascot = useJarvisMascotVisibility();
  const world = useThemeStore((s) => s.world);
  const setWorld = useThemeStore((s) => s.setWorld);
  const seenSeasonKeys = useThemeStore((s) => s.seenSeasonKeys);
  const [mounted, setMounted] = useState(false);

  // Motyw jest czytany z localStorage tylko w przeglądarce — bez rozjazdu hydracji.
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="h-9 w-9" aria-hidden />;
  }

  const activeWorld = THEME_WORLDS.find((w) => w.id === world);
  const forcedScheme = worldScheme(world);
  const season = activeSeason(companyDate());
  const seasonNew = Boolean(season && !seenSeasonKeys.includes(season.key));

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={seasonNew ? "Wygląd (nowy świat sezonowy)" : "Wygląd"}
          title="Wygląd: świat, motyw koloru, tryb ciemny, robot Jarvisa"
          className="relative h-9 w-9 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          data-tour="appearance.menu"
        >
          <Palette className="h-4 w-4" />
          {seasonNew && (
            <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-primary" data-testid="appearance-season-dot" aria-hidden />
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>Świat</DropdownMenuLabel>
        <DropdownMenuItem onSelect={openWorldGallery} className="cursor-pointer gap-2.5">
          {kidsMode ? (
            <Gamepad2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          ) : activeWorld ? (
            <span className={`world-swatch world-swatch-${activeWorld.id} h-4 w-4 shrink-0 rounded-full border border-black/10`} aria-hidden />
          ) : (
            <span className="h-4 w-4 shrink-0 rounded-full border border-dashed border-muted-foreground/50" aria-hidden />
          )}
          <span className="flex-1">{kidsMode ? "Gra" : activeWorld ? activeWorld.label : "Bez świata"}</span>
          {seasonNew && <span className="rounded bg-primary/10 px-1.5 text-[10px] font-semibold text-primary">nowe</span>}
          <span className="text-xs text-muted-foreground">Zmień</span>
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        </DropdownMenuItem>
        {(kidsMode || activeWorld) && (
          <DropdownMenuItem
            onSelect={() => {
              if (kidsMode) toggleKidsMode();
              setWorld("none");
            }}
            className="cursor-pointer gap-2.5"
          >
            <X className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="flex-1">Wyłącz świat</span>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        {activeWorld ? (
          <DropdownMenuItem disabled className="gap-2.5">
            <span className="flex-1 text-xs text-muted-foreground">Motyw koloru i tryb ciemny wybiera świat.</span>
          </DropdownMenuItem>
        ) : (
          <>
            <PaletteMenuItems />
            <DropdownMenuSeparator />
          </>
        )}
        {!forcedScheme && (
          <DropdownMenuItem
            role="menuitemcheckbox"
            aria-checked={theme === "dark"}
            onSelect={toggleTheme}
            className="cursor-pointer gap-2.5"
          >
            <Moon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="flex-1">Tryb ciemny</span>
            {theme === "dark" && <Check className="h-4 w-4 shrink-0 text-foreground" />}
          </DropdownMenuItem>
        )}
        {mascot.visible !== null && (
          <DropdownMenuItem
            role="menuitemcheckbox"
            aria-checked={mascot.visible}
            onSelect={() => mascot.setVisible(!mascot.visible)}
            className="cursor-pointer gap-2.5"
          >
            <Bot className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="flex-1">Robot Jarvisa w rogu</span>
            {mascot.visible && <Check className="h-4 w-4 shrink-0 text-foreground" />}
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
