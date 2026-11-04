/**
 * Szablony graficzne strony kariery — jedno źródło kolorów dla strony
 * (`CareerThemeScope` → zmienne `--kr-*`), grafik OG (`og.tsx`) i podglądu
 * posta w NEXUSIE (`LinkedInPreviewCard`).
 *
 * Od 28.10.2026 (decyzja Artura po feedbacku zespołu: „nieczytelne”, „nie
 * w szacie B2B”, „jakby się nie doładowało”) są trzy szablony zamiast 12 scen:
 * Terminal (role deweloperskie), Grafit (domyślny) i Jasny (role biznesowe),
 * każdy w barwach marki B2B Network. Makiety:
 * https://claude.ai/artifact/RGquQpMFyKgRYHPognJ2kU (A, C, B).
 *
 * Domyślny szablon rekrutacji liczy backend (`services/career_theme.py`: rola
 * z tytułu → kategoria → Grafit); lista identyfikatorów musi być ta sama —
 * pilnuje `__tests__/themes.test.ts`.
 *
 * Moduł bez zależności od Node — importuje go komponent kliencki.
 */
import type { OG_COLORS } from "./palette";

export const CAREER_THEME_IDS = ["grafit", "terminal", "jasny"] as const;

export type CareerThemeId = (typeof CAREER_THEME_IDS)[number];

export const DEFAULT_CAREER_THEME: CareerThemeId = "grafit";

/** Bazowa paleta szablonu; reszta tokenów wynika z niej (`themeTokens`). */
export interface ThemePalette {
  /** Nazwa w oknie „Udostępnij”. */
  label: string;
  /** Role, dla których szablon jest domyślny (podpis w oknie wyboru). */
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
  /** Duży tekst w czerwieni marki — ≥ 3:1. */
  title: string;
  /** Ozdobniki: kropki, punktory, paski. */
  decor: string;
  line: string;
  btn: string;
  /** Tekst na przycisku — ≥ 4,5:1 do `btn`. */
  btnText: string;
  light?: boolean;
}

// Czerwień marki #E73748 (brand book) zostaje na tytułach i ozdobnikach; przycisk
// #D62E40 jest o ton głębszy, bo biały tekst na #E73748 ma 4,2:1 (próg 4,5:1).
export const CAREER_THEMES: Record<CareerThemeId, ThemePalette> = {
  grafit: {
    label: "Grafit B2B",
    role: "Domyślny: architekt, data, infrastruktura, security",
    bg: "#141414",
    text: "#F5F4EC",
    heading: "#FFFFFF",
    muted: "#AAB4BF",
    para: "#D9D6CC",
    accent: "#F05A69",
    title: "#E73748",
    decor: "#E73748",
    line: "#2A2A2A",
    btn: "#D62E40",
    btnText: "#FFFFFF",
  },
  terminal: {
    label: "Terminal",
    role: "Programista, tester, DevOps",
    bg: "#161514",
    text: "#F1EEE6",
    heading: "#FFFFFF",
    muted: "#A8A39A",
    para: "#CFCAC0",
    accent: "#F05A69",
    title: "#E73748",
    decor: "#E73748",
    line: "#2C2A27",
    btn: "#D62E40",
    btnText: "#FFFFFF",
  },
  jasny: {
    label: "Jasny B2B",
    role: "Project manager, analityk, delivery",
    bg: "#F5F4EC",
    text: "#141414",
    heading: "#141414",
    muted: "#4A5056",
    para: "#2E3236",
    accent: "#C42536",
    title: "#C42536",
    decor: "#E73748",
    line: "#E1E1E1",
    btn: "#D62E40",
    btnText: "#FFFFFF",
    light: true,
  },
};

export function isCareerThemeId(value: unknown): value is CareerThemeId {
  return typeof value === "string" && (CAREER_THEME_IDS as readonly string[]).includes(value);
}

/** Identyfikator szablonu albo Grafit dla nieznanego (np. jednej z 12 dawnych scen). */
export function careerThemeId(id: string | null | undefined): CareerThemeId {
  return isCareerThemeId(id) ? id : DEFAULT_CAREER_THEME;
}

/** Nieznany albo pusty identyfikator = Grafit (strona nigdy bez wyglądu). */
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
 * Zmienne `--kr-*` szablonu. Każdy szablon (także Terminal od 28.10.2026)
 * nadpisuje czarne wartości z `career.css`; nieznany identyfikator = Grafit.
 */
export function themeTokens(id: string | null | undefined): Record<string, string> {
  const p = careerTheme(id);
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
  const p = careerTheme(id);
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
