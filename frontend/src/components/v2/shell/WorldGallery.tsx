"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Gamepad2, Sparkles } from "lucide-react";

import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { activeSeason, companyDate, worldAvailable } from "@/lib/worlds/seasons";
import { THEME_WORLDS, WORLD_CATEGORIES, useThemeStore, type WorldDef } from "@/store/theme";

import { useKidsModeToggle } from "./ThemeControls";

/**
 * Galeria światów (decyzja Artura 13.11.2026, `docs/claude/ui/swiaty-wygladu.md`).
 * Kilkanaście światów nie mieści się w menu „Wygląd”, więc menu pokazuje tylko
 * bieżący świat, a wybór jest tu: kafelki z miniaturą, pogrupowane po klimacie.
 * Klik zmienia wygląd od razu, na żywo za oknem. Galerię otwiera menu
 * „Wygląd”, szuflada na telefonie i dymek robota — przez `openWorldGallery()`.
 */

export const OPEN_WORLD_GALLERY_EVENT = "nexus:open-world-gallery";

export function openWorldGallery(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(OPEN_WORLD_GALLERY_EVENT));
}

/** Jedno okno galerii na całą aplikację (montowane w powłoce). */
export function WorldGalleryHost() {
  const [open, setOpen] = useState(false);
  const markSeasonSeen = useThemeStore((s) => s.markSeasonSeen);
  useEffect(() => {
    const onOpen = () => {
      setOpen(true);
      const season = activeSeason(companyDate());
      if (season) markSeasonSeen(season.key);
    };
    window.addEventListener(OPEN_WORLD_GALLERY_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_WORLD_GALLERY_EVENT, onOpen);
  }, [markSeasonSeen]);
  return <WorldGallery open={open} onOpenChange={setOpen} />;
}

interface WorldGalleryProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Testy: stała data zamiast dzisiejszej. */
  now?: Date;
}

export function WorldGallery({ open, onOpenChange, now }: WorldGalleryProps) {
  const world = useThemeStore((s) => s.world);
  const setWorld = useThemeStore((s) => s.setWorld);
  const { kidsMode, toggle: toggleKidsMode } = useKidsModeToggle();
  const noneActive = world === "none" && !kidsMode;
  const bodyRef = useRef<HTMLDivElement>(null);
  const today = companyDate(now);
  const season = activeSeason(today);
  const featured = new Set(season?.season.featured ?? []);

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
            <div className="flex flex-wrap items-center gap-3">
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
            {season && (
              <p className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-sm text-foreground">
                <Sparkles className="h-4 w-4 shrink-0 text-primary" aria-hidden />
                {season.season.label}: wyróżnione światy mają znaczek „Sezon”, {season.season.until}.
              </p>
            )}
            {WORLD_CATEGORIES.map((cat) => {
              const items = THEME_WORLDS.filter((w) => w.category === cat.id && worldAvailable(w.id, today));
              if (items.length === 0 && cat.id !== "kolorowe") return null;
              return (
                <section key={cat.id} className="flex flex-col gap-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{cat.label}</h3>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-6">
                    {cat.id === "kolorowe" && (
                      <WorldTile
                        id="game"
                        label="Gra"
                        hint="dzisiejszy tryb gry"
                        icon={<Gamepad2 className="h-3.5 w-3.5" aria-hidden />}
                        active={kidsMode}
                        onPick={pickGame}
                      />
                    )}
                    {items.map((w: WorldDef) => (
                      <WorldTile
                        key={w.id}
                        id={w.id}
                        label={w.label}
                        hint={w.hint}
                        dark={w.scheme === "dark"}
                        seasonal={featured.has(w.id)}
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
  id: string;
  label: string;
  hint: string;
  active: boolean;
  onPick: () => void;
  dark?: boolean;
  seasonal?: boolean;
  icon?: ReactNode;
}

function WorldTile({ id, label, hint, active, onPick, dark, seasonal, icon }: WorldTileProps) {
  return (
    <button
      type="button"
      onClick={onPick}
      aria-pressed={active}
      data-world-tile={id}
      className={cn(
        "group flex flex-col gap-1.5 rounded-lg p-1.5 text-left transition-colors",
        "hover:bg-muted focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        active && "ring-2 ring-primary"
      )}
    >
      <span
        className={`world-thumb-${id} relative block aspect-[16/9] w-full overflow-hidden rounded-md border border-border`}
        style={{ background: "var(--wt-bg)" }}
        aria-hidden
      >
        <span className="absolute inset-y-0 left-0 w-[22%]" style={{ background: "var(--wt-side)" }} />
        <span className="absolute left-[30%] top-[14%] h-[6%] w-[34%] rounded-sm opacity-85" style={{ background: "var(--wt-fg)" }} />
        <span className="absolute bottom-[12%] left-[30%] right-[8%] top-[30%] rounded-md shadow-sm" style={{ background: "var(--wt-card)" }}>
          <span className="absolute left-[8%] top-[16%] h-[9%] w-[46%] rounded-sm opacity-55" style={{ background: "var(--wt-fg)" }} />
          <span className="absolute left-[8%] top-[36%] h-[7%] w-[70%] rounded-sm opacity-20" style={{ background: "var(--wt-fg)" }} />
          <span className="absolute left-[8%] top-[52%] h-[7%] w-[58%] rounded-sm opacity-20" style={{ background: "var(--wt-fg)" }} />
          <span className="absolute bottom-[14%] left-[8%] h-[18%] w-[30%] rounded-sm" style={{ background: "var(--wt-primary)" }} />
        </span>
        {active && (
          <span className="absolute right-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Check className="h-3 w-3" />
          </span>
        )}
      </span>
      <span className="flex flex-wrap items-center gap-1.5 px-0.5 text-sm font-medium text-foreground">
        {icon}
        {label}
        {dark && <span className="rounded bg-muted px-1 text-[10px] font-medium text-muted-foreground">ciemny</span>}
        {seasonal && <span className="rounded bg-primary/10 px-1 text-[10px] font-semibold text-primary">Sezon</span>}
      </span>
      <span className="px-0.5 text-xs text-muted-foreground">{hint}</span>
    </button>
  );
}

/** Szuflada na telefonie: przycisk „Świat” zamiast osobnego przełącznika trybu gry. */
export function WorldGalleryButton() {
  const kidsMode = useThemeStore((s) => s.kidsMode);
  const world = useThemeStore((s) => s.world);
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return <div className="h-8 w-8" aria-hidden />;
  const on = kidsMode || world !== "none";
  return (
    <button
      type="button"
      onClick={openWorldGallery}
      aria-label="Wybierz świat"
      title="Świat"
      className={cn(
        "h-8 w-8 flex items-center justify-center rounded-md transition-colors",
        on ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      <Sparkles className="h-4 w-4" />
    </button>
  );
}
