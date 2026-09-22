import localFont from "next/font/local";

/**
 * Fonty strony kariery — self-hosted (patrz `src/app/fonts/README.md`).
 *
 * Nigdy `next/font/google`: Coolify buduje obraz przy każdym deployu, a awaria
 * Google Fonts wywalała build produkcyjny. Deklarowane tutaj (nie w root
 * layoucie), bo potrzebuje ich wyłącznie `/kariera` i harness `/preview/kariera`.
 */
export const careerDisplayFont = localFont({
  src: [
    { path: "../../app/fonts/Geist-700.woff2", weight: "700", style: "normal" },
    { path: "../../app/fonts/Geist-800.woff2", weight: "800", style: "normal" },
  ],
  variable: "--font-kr-display",
  display: "swap",
});

export const careerMonoFont = localFont({
  src: [
    { path: "../../app/fonts/JetBrainsMono-400.woff2", weight: "400", style: "normal" },
    { path: "../../app/fonts/JetBrainsMono-400-Italic.woff2", weight: "400", style: "italic" },
    { path: "../../app/fonts/JetBrainsMono-500.woff2", weight: "500", style: "normal" },
    { path: "../../app/fonts/JetBrainsMono-700.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-kr-mono",
  display: "swap",
});
