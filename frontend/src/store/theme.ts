import { create } from "zustand";
import { persist } from "zustand/middleware";

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

const PALETTE_IDS = new Set<ThemePalette>(THEME_PALETTES.map((p) => p.id));

export function isThemePalette(value: unknown): value is ThemePalette {
  return typeof value === "string" && PALETTE_IDS.has(value as ThemePalette);
}

interface ThemeState {
  theme: ThemeMode;
  palette: ThemePalette;
  /**
   * "Soft UI" depth mode — an orthogonal style dimension working with EVERY
   * color palette: tinted canvas, white raised cards with soft shadows and
   * rounder corners (see `html[data-soft="true"]` in globals.css). On by
   * default; "Klasyczny" in the palette picker switches back to the flat look.
   */
  softUi: boolean;
  /**
   * "Kids / game world" visual mode — a third, orthogonal dimension on top of
   * light/dark + palette. When on, a colorful playful skin takes over the whole
   * chrome (see `html[data-kids="true"]` in globals.css). Off by default.
   */
  kidsMode: boolean;
  /** Opt-in celebratory sound effects (Web Audio) while in Kids mode. */
  kidsSound: boolean;
  /** Opt-in: the mascot periodically speaks a slogan aloud on its own. */
  kidsAutoTalk: boolean;
  toggleTheme: () => void;
  setTheme: (theme: ThemeMode) => void;
  setPalette: (palette: ThemePalette) => void;
  setSoftUi: (enabled: boolean) => void;
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
      softUi: true,
      kidsMode: false,
      kidsSound: false,
      kidsAutoTalk: false,
      toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setTheme: (theme) => set({ theme }),
      setPalette: (palette) => set({ palette }),
      setSoftUi: (enabled) => set({ softUi: enabled }),
      toggleKidsMode: () => set((s) => ({ kidsMode: !s.kidsMode })),
      setKidsMode: (enabled) => set({ kidsMode: enabled }),
      toggleKidsSound: () => set((s) => ({ kidsSound: !s.kidsSound })),
      toggleKidsAutoTalk: () => set((s) => ({ kidsAutoTalk: !s.kidsAutoTalk })),
    }),
    {
      name: "nexus-theme",
      version: 8,
      // v3 had no `palette` field; v5 made indigo the default accent; v6 added
      // `kidsMode`; v7 added `softUi` (defaults to ON — the new depth look);
      // v8 dropped `kidsBuddy` — the mascot is Jarvis now and its character
      // lives in server-side preferences (`users.jarvis_prefs`).
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
        if (typeof next.softUi !== "boolean") {
          next.softUi = true;
        }
        delete (next as Record<string, unknown>).kidsBuddy;
        return next as ThemeState;
      },
    }
  )
);
