import { create } from "zustand";
import { persist } from "zustand/middleware";

import { isSeasonalWorld } from "@/lib/worlds/seasons";
import type { AccountWorldId } from "@/lib/worlds/world-ids";

export type ThemeMode = "light" | "dark";

/** Color palette (accent + chrome + sidebar). Orthogonal to light/dark mode. */
export type ThemePalette = "indigo" | "violet" | "blue" | "green" | "orange" | "rose" | "graphite";

export const THEME_PALETTES: ReadonlyArray<{
  id: ThemePalette;
  label: string;
  /** Representative swatch color (the accent), as a CSS color for the picker UI. */
  swatch: string;
}> = [
  { id: "indigo", label: "Indygo", swatch: "hsl(243 75% 56%)" },
  { id: "violet", label: "Fiolet", swatch: "hsl(263 70% 50%)" },
  { id: "blue", label: "Niebieski", swatch: "hsl(221 83% 53%)" },
  { id: "green", label: "Zielony", swatch: "hsl(142 71% 38%)" },
  { id: "orange", label: "Pomarańczowy", swatch: "hsl(24 90% 48%)" },
  { id: "rose", label: "Różowy", swatch: "hsl(346 77% 50%)" },
  { id: "graphite", label: "Grafit", swatch: "hsl(240 5% 34%)" },
];

/**
 * Świat wyglądu: cały wygląd naraz (tło, karty, nagłówki, kolory), obok trybu
 * gry. Decyzja Artura 13.11.2026, reguła `docs/claude/ui/swiaty-wygladu.md`.
 * Lista identyfikatorów ma lustro na serwerze (`lib/worlds/world-ids.ts`).
 */
export type ThemeWorld = Exclude<AccountWorldId, "game">;

export type WorldCategory = "spokojne" | "kolorowe" | "ciemne" | "sport" | "sezonowe";

export interface WorldDef {
  id: Exclude<ThemeWorld, "none">;
  label: string;
  hint: string;
  category: WorldCategory;
  /** Świat narzuca jasny albo ciemny schemat (klasa `.dark` na <html>). */
  scheme: "light" | "dark";
}

export const WORLD_CATEGORIES: ReadonlyArray<{ id: WorldCategory; label: string }> = [
  { id: "spokojne", label: "Jasne i spokojne" },
  { id: "kolorowe", label: "Kolorowe" },
  { id: "ciemne", label: "Ciemne" },
  { id: "sport", label: "Sport i przygoda" },
  { id: "sezonowe", label: "Sezonowe" },
];

export const THEME_WORLDS: ReadonlyArray<WorldDef> = [
  { id: "zen", label: "Zen", hint: "papier, bez animacji", category: "spokojne", scheme: "light" },
  { id: "latte", label: "Latte", hint: "kawiarnia, ciepłe brązy", category: "spokojne", scheme: "light" },
  { id: "lavender", label: "Lawenda", hint: "pole w Prowansji", category: "spokojne", scheme: "light" },
  { id: "botanic", label: "Botanika", hint: "liście monstery", category: "spokojne", scheme: "light" },
  { id: "marble", label: "Marmur i złoto", hint: "elegancko", category: "spokojne", scheme: "light" },
  { id: "sakura", label: "Sakura", hint: "kwitnąca wiśnia", category: "kolorowe", scheme: "light" },
  { id: "holo", label: "Holo", hint: "pastelowe Y2K", category: "kolorowe", scheme: "light" },
  { id: "sunset", label: "Zachód słońca", hint: "złota godzina", category: "kolorowe", scheme: "light" },
  { id: "retro", label: "Retro 8-bit", hint: "twarde cienie, kanciasto", category: "kolorowe", scheme: "light" },
  { id: "arcade", label: "Arcade", hint: "neonowa noc", category: "ciemne", scheme: "dark" },
  { id: "space", label: "Kosmos", hint: "gwiazdy i szkło", category: "ciemne", scheme: "dark" },
  { id: "rgb", label: "RGB", hint: "stanowisko gracza", category: "ciemne", scheme: "dark" },
  { id: "blueprint", label: "Blueprint", hint: "plan techniczny", category: "ciemne", scheme: "dark" },
  { id: "stadium", label: "Stadion", hint: "świat Ligi Mistrzów", category: "sport", scheme: "light" },
  { id: "pitstop", label: "Pit stop", hint: "włókno węglowe, szachownica", category: "sport", scheme: "dark" },
  { id: "mountains", label: "Góry", hint: "poziomice i szlak", category: "sport", scheme: "light" },
  { id: "winter", label: "Zima", hint: "śnieg i choinkowa zieleń", category: "sezonowe", scheme: "light" },
  { id: "tulips", label: "Tulipany", hint: "Dzień Kobiet", category: "sezonowe", scheme: "light" },
];

const WORLD_SCHEME = new Map<string, "light" | "dark">(THEME_WORLDS.map((w) => [w.id, w.scheme]));

/** Ciemne światy — lustro w skrypcie startowym `app/layout.tsx` (bez mignięcia). */
export const DARK_WORLD_IDS: ReadonlyArray<string> = THEME_WORLDS.filter((w) => w.scheme === "dark").map((w) => w.id);

export function worldScheme(world: ThemeWorld): "light" | "dark" | null {
  return world === "none" ? null : (WORLD_SCHEME.get(world) ?? null);
}

export function isThemeWorld(value: unknown): value is ThemeWorld {
  return value === "none" || (typeof value === "string" && WORLD_SCHEME.has(value));
}

const PALETTE_IDS = new Set<ThemePalette>(THEME_PALETTES.map((p) => p.id));

export function isThemePalette(value: unknown): value is ThemePalette {
  return typeof value === "string" && PALETTE_IDS.has(value as ThemePalette);
}

interface ThemeState {
  theme: ThemeMode;
  palette: ThemePalette;
  /**
   * "Kids / game world" visual mode — a third, orthogonal dimension on top of
   * light/dark + palette. When on, a colorful playful skin takes over the whole
   * chrome (see `html[data-kids="true"]` in globals.css). Off by default.
   */
  kidsMode: boolean;
  world: ThemeWorld;
  /** Świat sprzed sezonowego (Zima, Tulipany) — po sezonie wracamy do niego. */
  worldBeforeSeason: ThemeWorld | null;
  /** Sezony, które osoba już widziała w galerii (kropka „nowe”), np. „winter-2026”. */
  seenSeasonKeys: string[];
  /** Opt-in celebratory sound effects (Web Audio) while in Kids mode. */
  kidsSound: boolean;
  /** Opt-in: the mascot periodically speaks a slogan aloud on its own. */
  kidsAutoTalk: boolean;
  toggleTheme: () => void;
  setTheme: (theme: ThemeMode) => void;
  setPalette: (palette: ThemePalette) => void;
  /** Wybór z galerii. Wejście w świat sezonowy zapamiętuje poprzedni. */
  setWorld: (world: ThemeWorld) => void;
  /** Zapis z konta (serwer wygrywa przy wczytaniu) — bez dopisywania historii. */
  applyAccountWorld: (world: ThemeWorld, before: ThemeWorld | null, kids: boolean) => void;
  markSeasonSeen: (key: string) => void;
  toggleKidsMode: () => void;
  setKidsMode: (enabled: boolean) => void;
  toggleKidsSound: () => void;
  toggleKidsAutoTalk: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "light",
      palette: "indigo",
      kidsMode: false,
      world: "none",
      worldBeforeSeason: null,
      seenSeasonKeys: [],
      kidsSound: false,
      kidsAutoTalk: false,
      toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setTheme: (theme) => set({ theme }),
      setPalette: (palette) => set({ palette }),
      setWorld: (world) =>
        set((s) => ({
          world,
          kidsMode: world !== "none" ? false : s.kidsMode,
          worldBeforeSeason: isSeasonalWorld(world)
            ? isSeasonalWorld(s.world)
              ? s.worldBeforeSeason
              : s.kidsMode
                ? "none"
                : s.world
            : null,
        })),
      applyAccountWorld: (world, before, kids) =>
        set({ world: kids ? "none" : world, worldBeforeSeason: before, kidsMode: kids }),
      markSeasonSeen: (key) =>
        set((s) => (s.seenSeasonKeys.includes(key) ? s : { seenSeasonKeys: [...s.seenSeasonKeys, key].slice(-8) })),
      toggleKidsMode: () =>
        set((s) => ({ kidsMode: !s.kidsMode, ...(!s.kidsMode ? { world: "none" as const, worldBeforeSeason: null } : {}) })),
      setKidsMode: (enabled) => set({ kidsMode: enabled }),
      toggleKidsSound: () => set((s) => ({ kidsSound: !s.kidsSound })),
      toggleKidsAutoTalk: () => set((s) => ({ kidsAutoTalk: !s.kidsAutoTalk })),
    }),
    {
      name: "nexus-theme",
      version: 10,
      // v3 had no `palette` field; v5 made indigo the default accent; v6 added
      // `kidsMode`; v7 added `softUi` (defaults to ON — the new depth look);
      // v8 dropped `kidsBuddy` — the mascot is Jarvis now and its character
      // lives in server-side preferences (`users.jarvis_prefs`); v9 dropped
      // `softUi` — styl „Wyraźny” (cienie) jest stały, „Klasyczny” zniknął
      // z menu 13.11.2026 (decyzja Artura); v10 added `world`,
      // `worldBeforeSeason` and `seenSeasonKeys` (światy wyglądu).
      // Existing valid palettes (including "violet") are preserved — only
      // missing or unknown palettes fall back to indigo. `kidsMode` defaults
      // to false when absent.
      migrate: (persisted, version) => {
        const state = (persisted ?? {}) as Partial<ThemeState>;
        const next: Partial<ThemeState> = { ...state };
        if (version < 4 || !isThemePalette(state.palette)) {
          next.palette = "indigo";
        }
        if (typeof next.kidsMode !== "boolean") {
          next.kidsMode = false;
        }
        delete (next as Record<string, unknown>).kidsBuddy;
        delete (next as Record<string, unknown>).softUi;
        if (!isThemeWorld(next.world)) next.world = "none";
        if (!isThemeWorld(next.worldBeforeSeason)) next.worldBeforeSeason = null;
        if (!Array.isArray(next.seenSeasonKeys)) next.seenSeasonKeys = [];
        return next as ThemeState;
      },
    }
  )
);
