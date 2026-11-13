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

/** Świat — makieta 13.11.2026: cały wygląd naraz, obok trybu gry. */
export type ThemeWorld =
  | "none"
  | "arcade" | "stadium" | "space" | "zen" | "winter" | "retro"
  | "sakura" | "latte" | "lavender" | "botanic" | "marble" | "sunset" | "holo" | "tulips"
  | "pitstop" | "rgb" | "mountains" | "blueprint";

export type WorldCategory = "spokojne" | "kolorowe" | "ciemne" | "sport" | "sezonowe";

export interface WorldPreview {
  /** Tło płótna (dowolne tło CSS). */
  bg: string;
  sidebar: string;
  card: string;
  primary: string;
  fg: string;
}

export interface WorldDef {
  id: Exclude<ThemeWorld, "none">;
  label: string;
  hint: string;
  category: WorldCategory;
  /** Świat narzuca jasny albo ciemny schemat (klasa `.dark` na <html>). */
  scheme: "light" | "dark";
  /** Okno, w którym świat sezonowy jest w galerii, np. „1.12–6.01”. */
  season?: string;
  preview: WorldPreview;
}

export const WORLD_CATEGORIES: ReadonlyArray<{ id: WorldCategory; label: string }> = [
  { id: "spokojne", label: "Jasne i spokojne" },
  { id: "kolorowe", label: "Kolorowe" },
  { id: "ciemne", label: "Ciemne" },
  { id: "sport", label: "Sport i przygoda" },
  { id: "sezonowe", label: "Sezonowe" },
];

export const THEME_WORLDS: ReadonlyArray<WorldDef> = [
  { id: "zen", label: "Zen", hint: "papier, bez animacji", category: "spokojne", scheme: "light",
    preview: { bg: "#f4f1ea", sidebar: "#ebe6dc", card: "#fdfbf6", primary: "#47705d", fg: "#3a332b" } },
  { id: "latte", label: "Latte", hint: "kawiarnia, ciepłe brązy", category: "spokojne", scheme: "light",
    preview: { bg: "#f1e9de", sidebar: "#44301f", card: "#fdfaf5", primary: "#7a5130", fg: "#3a2a1c" } },
  { id: "lavender", label: "Lawenda", hint: "pole w Prowansji", category: "spokojne", scheme: "light",
    preview: { bg: "linear-gradient(180deg,#efeafd,#f3f0fb 60%,#e9e1f7)", sidebar: "#e9e3f7", card: "#ffffff", primary: "#6a47b8", fg: "#2e2347" } },
  { id: "botanic", label: "Botanika", hint: "liście monstery", category: "spokojne", scheme: "light",
    preview: { bg: "#ecf0e6", sidebar: "#1b3a2b", card: "#fdfdf8", primary: "#27674a", fg: "#173326" } },
  { id: "marble", label: "Marmur i złoto", hint: "elegancko", category: "spokojne", scheme: "light",
    preview: { bg: "linear-gradient(135deg,#f5f3f0,#e9e5df 45%,#f6f4f1)", sidebar: "#1e1c19", card: "#ffffff", primary: "#8a6623", fg: "#26231f" } },
  { id: "sakura", label: "Sakura", hint: "kwitnąca wiśnia", category: "kolorowe", scheme: "light",
    preview: { bg: "radial-gradient(circle at 100% 0,#fbd6e3,#fdf0f4 60%)", sidebar: "#fbe3ea", card: "#ffffff", primary: "#94386f", fg: "#3b1f2f" } },
  { id: "holo", label: "Holo", hint: "pastelowe Y2K", category: "kolorowe", scheme: "light",
    preview: { bg: "linear-gradient(125deg,#ffe0f2,#ece0ff 30%,#d9f3ff 60%,#d9f7ec 85%,#fff7d9)", sidebar: "#fbf2fd", card: "#ffffff", primary: "#9933cc", fg: "#2b2147" } },
  { id: "sunset", label: "Zachód słońca", hint: "złota godzina", category: "kolorowe", scheme: "light",
    preview: { bg: "linear-gradient(170deg,#ffe6c2,#fbd3c6 45%,#f3d0e3 78%,#e3d9f0)", sidebar: "#3b2a4d", card: "#ffffff", primary: "#b84a14", fg: "#2c2140" } },
  { id: "arcade", label: "Arcade", hint: "neonowa noc", category: "ciemne", scheme: "dark",
    preview: { bg: "#0b0a1c", sidebar: "#07061a", card: "#141233", primary: "#00e5ff", fg: "#d8f6fb" } },
  { id: "space", label: "Kosmos", hint: "gwiazdy i szkło", category: "ciemne", scheme: "dark",
    preview: { bg: "radial-gradient(circle at 85% 10%,#3b2a7a,#0c1030 60%)", sidebar: "#06081a", card: "#171c3d", primary: "#b28cff", fg: "#e6e9f9" } },
  { id: "rgb", label: "RGB", hint: "stanowisko gracza", category: "ciemne", scheme: "dark",
    preview: { bg: "radial-gradient(ellipse at 0 100%,#3b0f5c,#0e0e12 55%)", sidebar: "#0a0a0d", card: "#16161b", primary: "#1fd16b", fg: "#ecedf2" } },
  { id: "blueprint", label: "Blueprint", hint: "plan techniczny", category: "ciemne", scheme: "dark",
    preview: { bg: "#123a63", sidebar: "#0b2a4d", card: "#184a7a", primary: "#ffd53d", fg: "#eef6ff" } },
  { id: "stadium", label: "Stadion", hint: "świat Ligi Mistrzów", category: "sport", scheme: "light",
    preview: { bg: "repeating-linear-gradient(90deg,#e9f1ea 0 18px,#dfeae1 18px 36px)", sidebar: "#0d3a26", card: "#ffffff", primary: "#127a4c", fg: "#123024" } },
  { id: "pitstop", label: "Pit stop", hint: "włókno węglowe, szachownica", category: "sport", scheme: "dark",
    preview: { bg: "#151515", sidebar: "#0d0d0d", card: "#1b1b1b", primary: "#ff8a0a", fg: "#f2f2f2" } },
  { id: "mountains", label: "Góry", hint: "poziomice i szlak", category: "sport", scheme: "light",
    preview: { bg: "#f0ebe1", sidebar: "#1b3a30", card: "#fcfaf4", primary: "#21634a", fg: "#1a2f28" } },
  { id: "winter", label: "Zima", hint: "śnieg i choinkowa zieleń", category: "sezonowe", scheme: "light", season: "1.12–6.01",
    preview: { bg: "linear-gradient(180deg,#d3e6f6,#eef5fb 55%)", sidebar: "#14223f", card: "#ffffff", primary: "#1b7058", fg: "#16233b" } },
  { id: "tulips", label: "Tulipany", hint: "Dzień Kobiet", category: "sezonowe", scheme: "light", season: "1–8.03",
    preview: { bg: "linear-gradient(180deg,#eaf4fb,#fdf9ea 55%)", sidebar: "#21452f", card: "#ffffff", primary: "#2a6f45", fg: "#1b2d22" } },
];

/** Retro 8-bit zostaje w CSS, ale poza galerią (odradzany w makiecie). */
const WORLD_SCHEME: Record<Exclude<ThemeWorld, "none">, "light" | "dark"> = {
  ...Object.fromEntries(THEME_WORLDS.map((w) => [w.id, w.scheme])),
  retro: "light",
} as Record<Exclude<ThemeWorld, "none">, "light" | "dark">;

export function worldScheme(world: ThemeWorld): "light" | "dark" | null {
  return world === "none" ? null : WORLD_SCHEME[world];
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
  /** Opt-in celebratory sound effects (Web Audio) while in Kids mode. */
  kidsSound: boolean;
  /** Opt-in: the mascot periodically speaks a slogan aloud on its own. */
  kidsAutoTalk: boolean;
  toggleTheme: () => void;
  setTheme: (theme: ThemeMode) => void;
  setPalette: (palette: ThemePalette) => void;
  setWorld: (world: ThemeWorld) => void;
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
      kidsSound: false,
      kidsAutoTalk: false,
      toggleTheme: () => set((s) => ({ theme: s.theme === "light" ? "dark" : "light" })),
      setTheme: (theme) => set({ theme }),
      setPalette: (palette) => set({ palette }),
      setWorld: (world) => set({ world, ...(world !== "none" ? { kidsMode: false } : {}) }),
      toggleKidsMode: () => set((s) => ({ kidsMode: !s.kidsMode, ...(!s.kidsMode ? { world: "none" as const } : {}) })),
      setKidsMode: (enabled) => set({ kidsMode: enabled }),
      toggleKidsSound: () => set((s) => ({ kidsSound: !s.kidsSound })),
      toggleKidsAutoTalk: () => set((s) => ({ kidsAutoTalk: !s.kidsAutoTalk })),
    }),
    {
      name: "nexus-theme",
      version: 9,
      // v3 had no `palette` field; v5 made indigo the default accent; v6 added
      // `kidsMode`; v7 added `softUi` (defaults to ON — the new depth look);
      // v8 dropped `kidsBuddy` — the mascot is Jarvis now and its character
      // lives in server-side preferences (`users.jarvis_prefs`); v9 dropped
      // `softUi` — styl „Wyraźny” (cienie) jest stały, „Klasyczny” zniknął
      // z menu 13.11.2026 (decyzja Artura).
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
        return next as ThemeState;
      },
    }
  )
);
