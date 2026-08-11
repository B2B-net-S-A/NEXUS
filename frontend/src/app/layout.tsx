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
// in globals.css). One variable file declared under the same four discrete
// weights Google Fonts served for it, so the rendering is unchanged.
const fredoka = localFont({
  src: [
    { path: "./fonts/Fredoka-Variable.woff2", weight: "400", style: "normal" },
    { path: "./fonts/Fredoka-Variable.woff2", weight: "500", style: "normal" },
    { path: "./fonts/Fredoka-Variable.woff2", weight: "600", style: "normal" },
    { path: "./fonts/Fredoka-Variable.woff2", weight: "700", style: "normal" },
  ],
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
      className={`${inter.variable} ${poppins.variable} ${fredoka.variable}`}
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
