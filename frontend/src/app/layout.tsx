import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { QueryProvider } from "@/components/QueryProvider";
import { AppShellV2 } from "@/components/v2/shell/AppShellV2";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ToastProvider } from "@/components/Toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { KpiNudgeToaster } from "@/components/v2/kpi/KpiNudgeToaster";

// Fonts are self-hosted from `./fonts` on purpose — `next/font/google` fetches
// the .woff2 files from fonts.gstatic.com AT BUILD TIME, and Coolify rebuilds
// the image on every deploy, so a Google Fonts hiccup used to break production
// deploys (and CI), not just the dev machine. See ./fonts/README.md for
// provenance, licences and how to regenerate the files.
//
// Every file carries the latin AND latin-ext character sets in one woff2.
// latin-ext is required for Polish diacritics (ą ć ę ł ń ó ś ż ź) — without it
// the browser falls back to a system font for those glyphs, so Polish text
// renders in a visibly mismatched typeface across the whole app.
const inter = localFont({
  src: [{ path: "./fonts/Inter-Variable.woff2", weight: "100 900", style: "normal" }],
  variable: "--font-inter",
  display: "swap",
});

// Cyrillic lives in a SEPARATE file behind `unicode-range`, appended to the
// font stack rather than merged into the file above.
//
// The point of unicode-range is that the browser fetches this file only when it
// actually paints a character in the range — so a Polish-only session pays zero
// bytes for it. Merging Cyrillic into Inter-Variable.woff2 would instead charge
// every user ~33 KiB for glyphs almost none of them will ever see.
//
// Where it matters is not candidate names (CVs and LinkedIn give those in Latin
// transliteration) but `raw_cv_text` and recruiter notes, which store text as it
// arrived. One CV pasted in Ukrainian is enough to make the preview fall back to
// a system font mid-paragraph.
//
// The subset deliberately contains NO Latin glyphs, so it can never win a
// character that belongs to Inter — the stack order stays unambiguous.
const interCyrillic = localFont({
  src: [{ path: "./fonts/Inter-Cyrillic.woff2", weight: "100 900", style: "normal" }],
  variable: "--font-cyrillic",
  display: "swap",
  // Jeden literał, bez konkatenacji i bez stałej — `next/font` parsuje te
  // wartości statycznie ("Font loader values must be explicitly written
  // literals") i odrzuca nawet sklejenie dwóch stringów.
  //
  // Ta lista musi zgadzać się z zakresami użytymi przy generowaniu
  // Inter-Cyrillic.woff2 (patrz ./fonts/README.md). Rozjazd w jedną stronę
  // znaczy pobieranie pliku bez potrzeby, w drugą — znak bez glifu mimo
  // pobranego pliku.
  declarations: [
    {
      prop: "unicode-range",
      value:
        "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116,U+0460-052F,U+1C80-1C88,U+20B4,U+2DE0-2DFF,U+A640-A69F,U+FE2E-FE2F",
    },
  ],
});

const poppins = localFont({
  src: [
    { path: "./fonts/Poppins-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/Poppins-500.woff2", weight: "500", style: "normal" },
    { path: "./fonts/Poppins-600.woff2", weight: "600", style: "normal" },
    { path: "./fonts/Poppins-700.woff2", weight: "700", style: "normal" },
    { path: "./fonts/Poppins-800.woff2", weight: "800", style: "normal" },
  ],
  variable: "--font-poppins",
  display: "swap",
});

// Playful rounded font for the "Kids / game world" mode. Only used when
// [data-kids="true"] is set on <html> (it rebinds --font-inter / --font-poppins
// in globals.css). One variable file declared under four discrete weights.
//
// Baloo 2, NOT Fredoka. Fredoka is missing 14 of the 19 Polish diacritics — it
// carries only `ł ó Ł Ó` — and the kids theme swaps the font for the ENTIRE
// interface, not just headings. Since the browser substitutes per CHARACTER,
// words like "Rekrutację" or "Ścieżka" rendered with single letters in a
// different typeface, weight and width. Baloo 2 keeps the same chunky rounded
// character and covers Polish completely (verified glyph-by-glyph).
// Jeden wpis z ZAKRESEM wag, nie cztery kopie tej samej ścieżki. Cztery wpisy
// generują cztery bloki @font-face na ten sam plik i — co ważniejsze — ucinają
// oś na najwyższej zadeklarowanej wadze.
//
// Zakres sięga 800, a nie 700, bo tryb kids podmienia także `--font-poppins`,
// zadeklarowanego do 800. `font-extrabold` występuje w 22 plikach, m.in.
// w `HeroLigaMistrzow` i `ChampionsPodium` — czyli dokładnie na ekranach
// gamifikacji, gdzie ten motyw jest używany. Przy suficie 700 te nagłówki
// cicho spadały o dwie wagi. Oś Baloo 2 to `400..800`, więc pełny zakres jest
// tu darmowy.
const baloo2 = localFont({
  src: [{ path: "./fonts/Baloo2-Variable.woff2", weight: "400 800", style: "normal" }],
  variable: "--font-kids",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Nexus",
  description: "Modern recruitment platform for IT staffing agencies",
};

// Applied before first paint to prevent a flash of the wrong theme/palette.
// Mirrors the zustand-persist shape of `src/store/theme.ts` (key "nexus-theme").
const themeBootstrap = `(function(){try{var d=document.documentElement;var p="indigo",t="light",k=false,so=true;var raw=localStorage.getItem("nexus-theme");if(raw){var s=(JSON.parse(raw)||{}).state||{};if(s.theme==="dark"||s.theme==="light")t=s.theme;if(["indigo","violet","blue","green","orange","rose","graphite"].indexOf(s.palette)>=0)p=s.palette;if(s.kidsMode===true)k=true;if(s.softUi===false)so=false;}if(t==="dark")d.classList.add("dark");d.dataset.theme=p;if(k)d.dataset.kids="true";if(so)d.dataset.soft="true";}catch(e){var r=document.documentElement;r.dataset.theme="indigo";r.dataset.soft="true";}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="pl"
      suppressHydrationWarning
      className={`${inter.variable} ${interCyrillic.variable} ${poppins.variable} ${baloo2.variable}`}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body className="bg-background text-foreground font-sans antialiased">
        <QueryProvider>
          <ThemeProvider>
            <ToastProvider>
              <TooltipProvider delayDuration={200} skipDelayDuration={100}>
                <AppShellV2>{children}</AppShellV2>
                <KpiNudgeToaster />
              </TooltipProvider>
            </ToastProvider>
          </ThemeProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
