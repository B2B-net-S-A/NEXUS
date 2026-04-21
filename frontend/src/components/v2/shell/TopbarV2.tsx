"use client";

import { useEffect, useState } from "react";
import { Menu, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { BreadcrumbV2 } from "./BreadcrumbV2";
import { QuickActionsV2, type QuickActionModal } from "./QuickActionsV2";
import { CommandPaletteV2 } from "./CommandPaletteV2";
import { NotificationsDropdown } from "@/components/NotificationsDropdown";

interface Props {
  onOpenMobileSidebar: () => void;
  pendingModal: QuickActionModal;
  onClearPendingModal: () => void;
  onOpenCommandPalette: () => void;
}

/**
 * TopbarV2 — sticky top bar with breadcrumb, ⌘K search trigger, notifications,
 * quick actions, and profile. Height 56px. White surface on cream canvas.
 */
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
        "h-14 shrink-0 flex items-center gap-3 px-4 md:px-5",
        "bg-[hsl(var(--bg-surface))] border-b border-[hsl(var(--border-subtle))]",
        "shadow-v2-xs"
      )}
    >
      {/* Mobile hamburger */}
      <button
        onClick={onOpenMobileSidebar}
        aria-label="Otwórz menu"
        className="md:hidden h-9 w-9 flex items-center justify-center rounded-v2-s text-[hsl(var(--text-muted))] hover:bg-[hsl(var(--accent-soft))] hover:text-[hsl(var(--text-title))] transition-colors"
      >
        <Menu className="h-5 w-5" />
      </button>

      {/* Breadcrumb (desktop) */}
      <div className="hidden md:flex min-w-0 max-w-[360px] flex-1 md:flex-none">
        <BreadcrumbV2 />
      </div>

      {/* Command palette trigger (center, flex-1) */}
      <button
        onClick={onOpenCommandPalette}
        aria-label="Otwórz wyszukiwanie"
        className={cn(
          "flex-1 max-w-md mx-auto flex items-center gap-2 h-9 px-3",
          "rounded-v2-m border border-[hsl(var(--border-subtle))]",
          "bg-[hsl(var(--bg-canvas))]/60 hover:bg-[hsl(var(--bg-canvas))] transition-colors",
          "text-left text-sm text-[hsl(var(--text-muted))]"
        )}
      >
        <Search className="h-4 w-4 shrink-0" />
        <span className="truncate">Szukaj kandydatów, ofert, klientów…</span>
        <div className="ml-auto flex items-center gap-1 shrink-0">
          <Kbd>{isMac ? "⌘" : "Ctrl"}</Kbd>
          <Kbd>K</Kbd>
        </div>
      </button>

      {/* Right: notifications + quick actions */}
      <div className="flex items-center gap-2 shrink-0">
        <NotificationsDropdown />
        <QuickActionsV2
          externalModal={pendingModal}
          onExternalModalClear={onClearPendingModal}
        />
      </div>
    </header>
  );
}

// Re-export so AppShellV2 can wire open state
export { CommandPaletteV2 };
// Keep Button reference for tree-shaking hint (unused at runtime if not mounted)
export const _TopbarButton = Button;
