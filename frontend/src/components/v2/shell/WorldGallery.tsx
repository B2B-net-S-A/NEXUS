"use client";

import { useRef } from "react";
import { Check, Gamepad2 } from "lucide-react";

import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { THEME_WORLDS, WORLD_CATEGORIES, useThemeStore, type WorldDef, type WorldPreview } from "@/store/theme";

import { useKidsModeToggle } from "./ThemeControls";

/**
 * Galeria światów — MAKIETA 13.11.2026. Kilkanaście światów nie mieści się
 * w menu „Wygląd”, więc menu pokazuje tylko bieżący świat, a wybór jest tu:
 * kafelki z miniaturą, pogrupowane po klimacie. Klik zmienia wygląd od razu,
 * na żywo za oknem.
 */
const GAME_PREVIEW: WorldPreview = {
  bg: "linear-gradient(135deg,#e5f6ff,#f3e8ff 50%,#fff7d6)",
  sidebar: "#f3eaff",
  card: "#ffffff",
  primary: "#d61f7f",
  fg: "#2a2560",
};

interface WorldGalleryProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function WorldGallery({ open, onOpenChange }: WorldGalleryProps) {
  const world = useThemeStore((s) => s.world);
  const setWorld = useThemeStore((s) => s.setWorld);
  const { kidsMode, toggle: toggleKidsMode } = useKidsModeToggle();
  const noneActive = world === "none" && !kidsMode;
  const bodyRef = useRef<HTMLDivElement>(null);

  const pickNone = () => {
    if (kidsMode) toggleKidsMode();
    setWorld("none");
  };
  const pickGame = () => {
    if (!kidsMode) toggleKidsMode();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        size="2xl"
        aria-describedby="world-gallery-desc"
        onOpenAutoFocus={(e) => {
          // Fokus na wybranym świecie: okno samo przewija się do niego.
          const active = bodyRef.current?.querySelector<HTMLElement>('[aria-pressed="true"]');
          if (active) {
            e.preventDefault();
            active.focus();
          }
        }}
      >
        <DialogHeader>
          <DialogTitle>Wybierz świat</DialogTitle>
          <DialogDescription id="world-gallery-desc">
            Świat zmienia tło, karty, nagłówki i kolory. Układ, liczby i przyciski zostają na swoich miejscach.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div ref={bodyRef} className="flex flex-col gap-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={pickNone}
              aria-pressed={noneActive}
              className={cn(
                "inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm font-medium transition-colors",
                "hover:bg-muted focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                noneActive && "border-primary text-primary"
              )}
            >
              {noneActive && <Check className="h-4 w-4" aria-hidden />}
              Bez świata
            </button>
            <span className="text-xs text-muted-foreground">Zwykły wygląd z motywem koloru wybranym w menu.</span>
          </div>
          {WORLD_CATEGORIES.map((cat) => {
            const items = THEME_WORLDS.filter((w) => w.category === cat.id);
            return (
              <section key={cat.id} className="flex flex-col gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{cat.label}</h3>
                <div className="grid grid-cols-6 gap-2">
                  {cat.id === "kolorowe" && (
                    <WorldTile
                      label="Gra"
                      hint="dzisiejszy tryb gry"
                      icon={<Gamepad2 className="h-3.5 w-3.5" aria-hidden />}
                      preview={GAME_PREVIEW}
                      active={kidsMode}
                      onPick={pickGame}
                    />
                  )}
                  {items.map((w: WorldDef) => (
                    <WorldTile
                      key={w.id}
                      label={w.label}
                      hint={w.hint}
                      season={w.season}
                      dark={w.scheme === "dark"}
                      preview={w.preview}
                      active={!kidsMode && world === w.id}
                      onPick={() => setWorld(w.id)}
                    />
                  ))}
                </div>
              </section>
            );
          })}
          </div>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

interface WorldTileProps {
  label: string;
  hint: string;
  preview: WorldPreview;
  active: boolean;
  onPick: () => void;
  season?: string;
  dark?: boolean;
  icon?: React.ReactNode;
}

function WorldTile({ label, hint, preview, active, onPick, season, dark, icon }: WorldTileProps) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={active}
      className={cn(
        "group flex flex-col gap-1.5 rounded-lg p-1.5 text-left transition-colors",
        "hover:bg-muted focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        active && "ring-2 ring-primary"
      )}
    >
      <span
        className="relative block aspect-[16/9] w-full overflow-hidden rounded-md border border-black/10"
        style={{ background: preview.bg }}
        aria-hidden
      >
        <span className="absolute inset-y-0 left-0 w-[22%]" style={{ background: preview.sidebar }} />
        <span className="absolute left-[30%] top-[14%] h-[6%] w-[34%] rounded-sm" style={{ background: preview.fg, opacity: 0.85 }} />
        <span
          className="absolute left-[30%] right-[8%] top-[30%] bottom-[12%] rounded-md shadow-sm"
          style={{ background: preview.card }}
        >
          <span className="absolute left-[8%] top-[16%] h-[9%] w-[46%] rounded-sm" style={{ background: preview.fg, opacity: 0.55 }} />
          <span className="absolute left-[8%] top-[36%] h-[7%] w-[70%] rounded-sm" style={{ background: preview.fg, opacity: 0.2 }} />
          <span className="absolute left-[8%] top-[52%] h-[7%] w-[58%] rounded-sm" style={{ background: preview.fg, opacity: 0.2 }} />
          <span className="absolute bottom-[14%] left-[8%] h-[18%] w-[30%] rounded-sm" style={{ background: preview.primary }} />
        </span>
        {active && (
          <span className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Check className="h-3 w-3" />
          </span>
        )}
      </span>
      <span className="flex items-center gap-1.5 px-0.5 text-sm font-medium text-foreground">
        {icon}
        {label}
        {dark && <span className="rounded bg-muted px-1 text-[10px] font-medium text-muted-foreground">ciemny</span>}
        {season && <span className="rounded bg-muted px-1 text-[10px] font-medium text-muted-foreground">{season}</span>}
      </span>
      <span className="px-0.5 text-xs text-muted-foreground">{hint}</span>
    </button>
  );
}
