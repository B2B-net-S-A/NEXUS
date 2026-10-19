/**
 * Szablony graficzne strony kariery (0478, 19.10.2026) — jedno źródło kolorów
 * dla strony (`CareerThemeScope` → zmienne `--kr-*`), grafik OG (`og.tsx`)
 * i podglądu posta w NEXUSIE (`LinkedInPreviewCard`).
 *
 * Domyślny szablon rekrutacji liczy backend (`services/career_theme.py`: rola
 * z tytułu → kategoria → Terminal); lista identyfikatorów musi być ta sama —
 * pilnuje `__tests__/themes.test.ts`. Makiety:
 * https://claude.ai/artifact/TFqDt54DUg4qRdyJXnu6wm (strona „Najczęstsze role”).
 *
 * Moduł bez zależności od Node — importuje go komponent kliencki.
 */
import { OG_COLORS } from "./palette";

export const CAREER_THEME_IDS = [
  "terminal",
  "sekwencja",
  "glitch",
  "konstelacja",
  "c4",
  "topologia",
  "tablica",
  "plan",
  "papier",
  "radar",
  "horyzont",
  "szafa",
] as const;

export type CareerThemeId = (typeof CAREER_THEME_IDS)[number];

export const DEFAULT_CAREER_THEME: CareerThemeId = "terminal";

/** Bazowa paleta szablonu; reszta tokenów wynika z niej (`themeTokens`). */
export interface ThemePalette {
  /** Nazwa w oknie „Udostępnij”. */
  label: string;
  /** Rola, dla której szablon jest domyślny (podpis w oknie wyboru). */
  role: string;
  bg: string;
  /** Tekst główny. */
  text: string;
  /** Pierwsza linia tytułu, mocne napisy. */
  heading: string;
  /** Drugorzędny tekst (`.kr-g`) — ≥ 4,5:1. */
  muted: string;
  /** Akapity opisu — ≥ 4,5:1. */
  para: string;
  /** Drobny tekst akcentu i linki — ≥ 4,5:1. */
  accent: string;
  /** Druga linia tytułu — ≥ 3:1 (duży tekst). */
  title: string;
  /** Ozdobniki: kropki, punktory, paski. */
  decor: string;
  line: string;
  btn: string;
  /** Tekst na przycisku — ≥ 4,5:1 do `btn`. */
  btnText: string;
  light?: boolean;
}

export const CAREER_THEMES: Record<CareerThemeId, ThemePalette> = {
  terminal: {
    label: "Terminal",
    role: "Programista",
    bg: OG_COLORS.bg,
    text: OG_COLORS.text,
    heading: OG_COLORS.white,
    muted: OG_COLORS.gray,
    para: "#A5A5A5",
    accent: OG_COLORS.red,
    title: OG_COLORS.title,
    decor: OG_COLORS.bordo,
    line: OG_COLORS.line,
    btn: OG_COLORS.bordo,
    btnText: OG_COLORS.white,
  },
  sekwencja: {
    label: "Diagram sekwencji",
    role: "Analityk systemowy",
    bg: "#0F1222",
    text: "#EEF1FF",
    heading: "#FFFFFF",
    muted: "#9CA3C8",
    para: "#CBD0EE",
    accent: "#A78BFA",
    title: "#A78BFA",
    decor: "#A78BFA",
    line: "#22284A",
    btn: "#A78BFA",
    btnText: "#0F1222",
  },
  glitch: {
    label: "Glitch",
    role: "Tester automatyzujący",
    bg: "#0A0A0A",
    text: "#FAFAFA",
    heading: "#FFFFFF",
    muted: "#9A9A9A",
    para: "#C8C8C8",
    accent: "#00E1FF",
    title: "#00E1FF",
    decor: "#FF4D6A",
    line: "#1E1E1E",
    btn: "#00E1FF",
    btnText: "#0A0A0A",
  },
  konstelacja: {
    label: "Konstelacja",
    role: "Data / AI",
    bg: "#070A1A",
    text: "#EEF0FF",
    heading: "#FFFFFF",
    muted: "#9AA0C4",
    para: "#C9CDEA",
    accent: "#F4D58D",
    title: "#F4D58D",
    decor: "#A9B4FF",
    line: "#1A1F3D",
    btn: "#F4D58D",
    btnText: "#070A1A",
  },
  c4: {
    label: "Architektura C4",
    role: "Architekt",
    bg: "#0B0F14",
    text: "#E8EEF4",
    heading: "#FFFFFF",
    muted: "#9AA7B4",
    para: "#C8D2DC",
    accent: "#FF8A65",
    title: "#FF8A65",
    decor: "#93C5FD",
    line: "#1A232D",
    btn: "#FF8A65",
    btnText: "#0B0F14",
  },
  topologia: {
    label: "Topologia sieci",
    role: "DevOps / Cloud",
    bg: "#0A0E14",
    text: "#F1F5F9",
    heading: "#FFFFFF",
    muted: "#94A3B8",
    para: "#C3CDD9",
    accent: "#FFA94D",
    title: "#FFA94D",
    decor: "#6CB8FF",
    line: "#1C2633",
    btn: "#FFA94D",
    btnText: "#0A0E14",
  },
  tablica: {
    label: "Tablica warsztatowa",
    role: "Analityk biznesowy",
    bg: "#13110E",
    text: "#F7F3EC",
    heading: "#FFFFFF",
    muted: "#B3AA9C",
    para: "#DDD5C8",
    accent: "#FFC857",
    title: "#FFC857",
    decor: "#7BDFF2",
    line: "#2A251E",
    btn: "#FFC857",
    btnText: "#13110E",
  },
  plan: {
    label: "Plan",
    role: "Project Manager, Scrum, PMO",
    bg: "#0B2A4A",
    text: "#FFFFFF",
    heading: "#FFFFFF",
    muted: "#A9C4E0",
    para: "#D3E3F3",
    accent: "#9CD3FF",
    title: "#9CD3FF",
    decor: "#FFD27A",
    line: "#24507E",
    btn: "#FFD27A",
    btnText: "#0B2A4A",
  },
  papier: {
    label: "Papier",
    role: "Tester manualny",
    bg: "#F5F3EE",
    text: "#1A1A1A",
    heading: "#1A1A1A",
    muted: "#5E5A52",
    para: "#3B3832",
    accent: "#C8102E",
    title: "#C8102E",
    decor: "#1F5FAD",
    line: "#DDD6C8",
    btn: "#C8102E",
    btnText: "#FFFFFF",
    light: true,
  },
  radar: {
    label: "Radar",
    role: "Security",
    bg: "#04120F",
    text: "#E6FFF6",
    heading: "#FFFFFF",
    muted: "#8DB5A8",
    para: "#BFDCD2",
    accent: "#43F5B5",
    title: "#43F5B5",
    decor: "#F5C451",
    line: "#123A31",
    btn: "#43F5B5",
    btnText: "#04120F",
  },
  horyzont: {
    label: "Horyzont",
    role: "Frontend, fullstack",
    bg: "#0A0614",
    text: "#F5F0FF",
    heading: "#FFFFFF",
    muted: "#A99BC4",
    para: "#D2C8E6",
    accent: "#FF6AD5",
    title: "#FF6AD5",
    decor: "#5EE7FF",
    line: "#22163A",
    btn: "#FF6AD5",
    btnText: "#0A0614",
  },
  szafa: {
    label: "Szafa serwerowa",
    role: "Administrator",
    bg: "#0A0C0F",
    text: "#E6EBF0",
    heading: "#FFFFFF",
    muted: "#8B97A5",
    para: "#C3CCD6",
    accent: "#60A5FA",
    title: "#60A5FA",
    decor: "#34D399",
    line: "#1A2029",
    btn: "#60A5FA",
    btnText: "#0A0C0F",
  },
};

export function isCareerThemeId(value: unknown): value is CareerThemeId {
  return typeof value === "string" && (CAREER_THEME_IDS as readonly string[]).includes(value);
}

/** Nieznany albo pusty identyfikator = Terminal (strona nigdy bez wyglądu). */
export function careerTheme(id: string | null | undefined): ThemePalette {
  return CAREER_THEMES[isCareerThemeId(id) ? id : DEFAULT_CAREER_THEME];
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
}

/** Mieszanka dwóch kolorów hex (`t` = udział drugiego). */
export function mixHex(a: string, b: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  const ch = (x: number, y: number) =>
    Math.round(x + (y - x) * t)
      .toString(16)
      .padStart(2, "0");
  return `#${ch(ar, br)}${ch(ag, bg)}${ch(ab, bb)}`.toUpperCase();
}

/**
 * Zmienne `--kr-*` szablonu. Terminal zwraca pusty obiekt — zostają wartości
 * z `career.css` (dzisiejszy wygląd bez żadnej zmiany).
 */
export function themeTokens(id: string | null | undefined): Record<string, string> {
  if (!isCareerThemeId(id) || id === DEFAULT_CAREER_THEME) return {};
  const p = CAREER_THEMES[id];
  return {
    "--kr-bg": p.bg,
    "--kr-grid": mixHex(p.bg, p.text, 0.04),
    "--kr-text": p.text,
    "--kr-white": p.heading,
    "--kr-gray": p.muted,
    "--kr-comment": p.muted,
    "--kr-para": p.para,
    "--kr-line": p.line,
    "--kr-line-strong": mixHex(p.bg, p.text, 0.16),
    "--kr-dim": mixHex(p.bg, p.text, 0.42),
    "--kr-bordo": p.decor,
    "--kr-bar": mixHex(p.bg, p.decor, 0.55),
    "--kr-red": p.accent,
    "--kr-title": p.title,
    "--kr-link": p.accent,
    "--kr-link-hover": p.heading,
    "--kr-err": p.accent,
    "--kr-form-bg": mixHex(p.bg, p.text, 0.015),
    "--kr-input-bg": mixHex(p.bg, p.text, 0.03),
    "--kr-tint": mixHex(p.bg, p.accent, 0.07),
    "--kr-tint-strong": mixHex(p.bg, p.accent, 0.11),
    "--kr-btn": p.btn,
    "--kr-btn-hover": mixHex(p.btn, p.heading, 0.15),
    "--kr-btn-text": p.btnText,
    "--kr-scheme": p.light ? "light" : "dark",
  };
}

/** Kolory grafiki OG w kształcie `OG_COLORS` — ten sam rysunek ramki. */
export function ogColors(id: string | null | undefined): Record<keyof typeof OG_COLORS, string> {
  if (!isCareerThemeId(id) || id === DEFAULT_CAREER_THEME) return { ...OG_COLORS };
  const p = CAREER_THEMES[id];
  return {
    bg: p.bg,
    grid: mixHex(p.bg, p.text, 0.05),
    line: p.line,
    text: p.text,
    white: p.heading,
    gray: p.muted,
    comment: p.muted,
    dim: mixHex(p.bg, p.text, 0.42),
    bordo: p.decor,
    red: p.accent,
    title: p.title,
  };
}
