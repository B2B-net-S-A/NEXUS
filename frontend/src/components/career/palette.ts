/**
 * Paleta strony kariery — jedno źródło dla grafik Open Graph (`og.tsx`)
 * i podglądu posta w NEXUSIE (`LinkedInPreviewCard`). Strona czyta te same
 * wartości jako zmienne `--kr-*` z `career.css`; zgodność pilnuje test
 * `__tests__/palette.test.ts`.
 *
 * Moduł bez zależności od Node (`og.tsx` czyta fonty z dysku), żeby mógł go
 * zaimportować komponent kliencki.
 *
 * Kontrast na czarnym tle (WCAG): `bordo` ≈ 2,5:1 — tylko tło pod białym
 * tekstem i ozdobniki; `title` ≈ 7:1 — czerwony w tekście tytułów (etap 5,
 * makieta 5a); `red` ≈ 4,9:1 — drobny tekst akcentu.
 */
export const OG_COLORS = {
  bg: "#000000",
  grid: "#0C0C0C",
  line: "#1A1A1A",
  text: "#F5F5F5",
  white: "#FFFFFF",
  gray: "#8B8B8B",
  comment: "#737373",
  dim: "#5C5C5C",
  bordo: "#9A142D",
  red: "#D14A5F",
  title: "#F06A80",
} as const;

export type CareerColor = keyof typeof OG_COLORS;
