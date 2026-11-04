"use client";

import { useEffect, useState } from "react";
import { Bot, Check, Gamepad2, Moon, Palette } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useJarvisMascotVisibility } from "@/components/jarvis/useJarvisMascotVisibility";
import { useThemeStore } from "@/store/theme";

import { PaletteMenuItems } from "./PaletteSwitcher";
import { useKidsModeToggle } from "./ThemeControls";

/**
 * „Wygląd” w górnym pasku: motyw koloru, styl interfejsu, tryb gry i tryb
 * ciemny w jednym menu (decyzja Artura 13.10.2026). Trzy osobne przyciski
 * po 32 px zabierały 112 px — to miejsce zajmuje przycisk Ligi Mistrzów.
 * Na telefonie przełączniki zostają osobno w szufladzie nawigacji.
 * „Robot Jarvisa w rogu” — tu się go przywraca po „Schowaj” na samym robocie.
 */
export function AppearanceMenu() {
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const { kidsMode, toggle: toggleKidsMode } = useKidsModeToggle();
  const mascot = useJarvisMascotVisibility();
  const [mounted, setMounted] = useState(false);

  // Motyw jest czytany z localStorage tylko w przeglądarce — bez rozjazdu hydracji.
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="h-9 w-9" aria-hidden />;
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label="Wygląd"
          title="Wygląd: motyw koloru, tryb gry, tryb ciemny, robot Jarvisa"
          className="h-9 w-9 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
        >
          <Palette className="h-4 w-4" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <PaletteMenuItems />
        <DropdownMenuSeparator />
        {/* Układ jak pozycje palety (znacznik po prawej); rola mówi czytnikowi o stanie. */}
        <DropdownMenuItem
          role="menuitemcheckbox"
          aria-checked={kidsMode}
          onSelect={toggleKidsMode}
          className="cursor-pointer gap-2.5"
        >
          <Gamepad2 className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
          <span className="flex-1">Tryb gry</span>
          {kidsMode && <Check className="h-4 w-4 shrink-0 text-foreground" />}
        </DropdownMenuItem>
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
