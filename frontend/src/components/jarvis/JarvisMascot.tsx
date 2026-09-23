"use client";

/**
 * Pływająca maskotka Jarvisa (prawy dolny róg): klik otwiera rozmowę, dymek
 * pokazuje krótkie komunikaty (poranny skrót dnia, reakcje w trybie kids).
 * Prezentacyjna — stan i akcje z propsów.
 */

import { X } from "lucide-react";
import type { JarvisAccent, JarvisCharacterId, JarvisMood } from "@/lib/jarvis/types";
import { JarvisCharacter } from "./characters/JarvisCharacter";

interface Props {
  name: string;
  character: JarvisCharacterId;
  accent: JarvisAccent;
  mood: JarvisMood;
  minimized: boolean;
  open: boolean;
  bubble?: string | null;
  attention?: boolean;
  onToggle: () => void;
  onBubbleClick?: () => void;
  onDismissBubble?: () => void;
  /** Harness `/preview/jarvis`: maskotka w przepływie strony zamiast `fixed`. */
  inline?: boolean;
}

export function JarvisMascot({
  name,
  character,
  accent,
  mood,
  minimized,
  open,
  bubble,
  attention = false,
  onToggle,
  onBubbleClick,
  onDismissBubble,
  inline = false,
}: Props) {
  const size = minimized ? 40 : 64;
  return (
    <div
      className={`pointer-events-none flex items-end gap-2 ${
        inline
          ? "relative"
          : "fixed bottom-[calc(1rem+env(safe-area-inset-bottom))] right-[calc(1rem+env(safe-area-inset-right))] z-30 sm:bottom-5 sm:right-5"
      }`}
    >
      {bubble && !open && (
        <div className="pointer-events-auto mb-8 flex max-w-[min(240px,calc(100vw-6rem))] items-start gap-1 rounded-2xl border border-primary/30 bg-card px-3 py-2 text-sm text-foreground shadow-lg">
          <button type="button" onClick={onBubbleClick} className="text-left">
            {bubble}
          </button>
          {onDismissBubble && (
            <button
              type="button"
              onClick={onDismissBubble}
              aria-label="Ukryj"
              className="hit-area -mr-1 -mt-0.5 rounded p-0.5 text-muted-foreground hover:bg-muted"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      )}
      <button
        type="button"
        onClick={onToggle}
        aria-label={open ? `Zamknij ${name}` : `Otwórz asystenta ${name} (⌘J)`}
        aria-expanded={open}
        title={open ? `Zamknij ${name}` : `${name} — asystent (⌘J)`}
        className="pointer-events-auto relative rounded-full outline-hidden transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="jarvis-mascot"
      >
        {/* Na telefonie postać 40 px — 64 px leżało na treści <main>. */}
        <JarvisCharacter
          id={character}
          accent={accent}
          mood={mood}
          size={size}
          className={inline ? undefined : "max-md:[&>svg]:size-10"}
        />
        {attention && !open && (
          <span className="absolute right-0 top-0 h-3 w-3 rounded-full border-2 border-card bg-destructive" aria-hidden />
        )}
      </button>
    </div>
  );
}
