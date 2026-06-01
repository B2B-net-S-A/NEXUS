"use client";

import { useEffect, useState } from "react";
import { Menu, Moon, Search, Sun } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { BreadcrumbV2 } from "./BreadcrumbV2";
import { QuickActionsV2, type QuickActionModal } from "./QuickActionsV2";
import { CommandPaletteV2 } from "./CommandPaletteV2";
import { NotificationsDropdown } from "@/components/NotificationsDropdown";
import { MyKpiWidget } from "@/components/v2/kpi/MyKpiWidget";
import { PaletteSwitcher } from "./PaletteSwitcher";
import { useThemeStore } from "@/store/theme";

function ThemeToggleButton() {
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

interface Props {
  onOpenMobileSidebar: () => void;
  pendingModal: QuickActionModal;
  onClearPendingModal: () => void;
  onOpenCommandPalette: () => void;
}

export function TopbarV2({
  onOpenMobileSidebar,
  pendingModal,
  onClearPendingModal,
  onOpenCommandPalette,
}: Props) {
  const [isMac, setIsMac] = useState(false);

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      setIsMac(/Mac|iPhone|iPad|iPod/.test(navigator.platform));
    }
  }, []);

  return (
    <header
      className={cn(
        "h-12 shrink-0 flex items-center gap-3 px-4 md:px-5",
        "bg-background border-b border-border"
      )}
    >
      <button
        onClick={onOpenMobileSidebar}
        aria-label="Otwórz menu"
        className="md:hidden h-8 w-8 flex items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      >
        <Menu className="h-4 w-4" />
      </button>

      <div className="hidden md:flex min-w-0 max-w-[360px] flex-1 md:flex-none">
        <BreadcrumbV2 />
      </div>

      <button
        onClick={onOpenCommandPalette}
        aria-label="Otwórz wyszukiwanie"
        className={cn(
          "flex-1 max-w-md mx-auto flex items-center gap-2 h-8 px-3",
          "rounded-md border border-border",
          "bg-muted/50 hover:bg-muted transition-colors",
          "text-left text-sm text-muted-foreground"
        )}
      >
        <Search className="h-4 w-4 shrink-0" />
        <span className="truncate">Szukaj kandydatów, ofert, klientów…</span>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          <Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd>
          <Kbd>K</Kbd>
        </div>
      </button>

      <div className="flex items-center gap-2 shrink-0">
        <MyKpiWidget variant="compact" className="hidden md:block" />
        <PaletteSwitcher />
        <ThemeToggleButton />
        <NotificationsDropdown />
        <QuickActionsV2
          externalModal={pendingModal}
          onExternalModalClear={onClearPendingModal}
        />
      </div>
    </header>
  );
}

export { CommandPaletteV2 };
export const _TopbarButton = Button;
