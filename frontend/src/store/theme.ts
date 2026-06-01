import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark";

/** Color palette (accent + chrome + sidebar). Orthogonal to light/dark mode. */
export type ThemePalette = "violet" | "blue" | "green" | "orange" | "rose" | "graphite";

export const THEME_PALETTES: ReadonlyArray<{
  id: ThemePalette;
  label: string;
  /** Representative swatch color (the accent), as a CSS color for the picker UI. */
  swatch: string;
}> = [
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
  toggleTheme: () => void;
  setTheme: (theme: ThemeMode) => void;
  setPalette: (palette: ThemePalette) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "light",
      palette: "violet",
      toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setTheme: (theme) => set({ theme }),
      setPalette: (palette) => set({ palette }),
    }),
    {
      name: "nexus-theme",
      version: 4,
      // v3 had no `palette` field — default it to the established violet accent.
      migrate: (persisted, version) => {
        const state = (persisted ?? {}) as Partial<ThemeState>;
        if (version < 4 || !isThemePalette(state.palette)) {
          return { ...state, palette: "violet" } as ThemeState;
        }
        return state as ThemeState;
      },
    }
  )
);
