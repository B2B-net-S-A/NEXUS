"use client";

import { useEffect, useState } from "react";
import { Gamepad2, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { useThemeStore } from "@/store/theme";
import { celebrate } from "@/lib/celebrate";

/**
 * Przełączniki wyglądu (tryb ciemny, tryb gry). Stoją w pasku górnym od
 * `sm`, a na telefonie w szufladzie nawigacji — pasek 375 px ich nie mieści
 * (audyt responsywności 23.09.2026).
 */
export function ThemeToggleButton() {
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch — theme is read from localStorage on client only.
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="h-8 w-8" aria-hidden />;
  }

  const isDark = theme === "dark";
  return (
    <button
      onClick={toggleTheme}
      aria-label={isDark ? "Włącz tryb jasny" : "Włącz tryb ciemny"}
      title={isDark ? "Tryb jasny" : "Tryb ciemny"}
      className="h-8 w-8 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
    >
      {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

export function KidsModeToggleButton() {
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const toggleKidsMode = useThemeStore((s) => s.toggleKidsMode);
  const [mounted, setMounted] = useState(false);

  // Avoid hydration mismatch — kidsMode is read from localStorage on client only.
  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return <div className="h-8 w-8" aria-hidden />;
  }

  const onToggle = () => {
    const turningOn = !kidsMode;
    toggleKidsMode();
    // Welcome burst when entering the game world (celebrate reads the freshly
    // set state, so it fires only on enable).
    if (turningOn) celebrate({ variant: "welcome", message: "Witaj w grze! 🎮" });
  };

  return (
    <button
      onClick={onToggle}
      aria-label={kidsMode ? "Wyłącz tryb gry" : "Włącz tryb gry (Kids)"}
      title={kidsMode ? "Wyłącz tryb gry" : "Tryb gry (Kids)"}
      aria-pressed={kidsMode}
      className={cn(
        "h-8 w-8 flex items-center justify-center rounded-md transition-colors",
        kidsMode
          ? "bg-primary/10 text-primary"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      <Gamepad2 className="h-4 w-4" />
    </button>
  );
}
