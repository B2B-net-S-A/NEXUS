import type { Metadata } from "next";
import { Inter, Poppins } from "next/font/google";
import "./globals.css";
import { QueryProvider } from "@/components/QueryProvider";
import { AppShellV2 } from "@/components/v2/shell/AppShellV2";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ToastProvider } from "@/components/Toast";
import { TooltipProvider } from "@/components/ui/tooltip";
import { KpiNudgeToaster } from "@/components/v2/kpi/KpiNudgeToaster";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const poppins = Poppins({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  variable: "--font-poppins",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Nexus",
  description: "Modern recruitment platform for IT staffing agencies",
};

// Applied before first paint to prevent a flash of the wrong theme/palette.
// Mirrors the zustand-persist shape of `src/store/theme.ts` (key "nexus-theme").
const themeBootstrap = `(function(){try{var d=document.documentElement;var p="indigo",t="light";var raw=localStorage.getItem("nexus-theme");if(raw){var s=(JSON.parse(raw)||{}).state||{};if(s.theme==="dark"||s.theme==="light")t=s.theme;if(["indigo","violet","blue","green","orange","rose","graphite"].indexOf(s.palette)>=0)p=s.palette;}if(t==="dark")d.classList.add("dark");d.dataset.theme=p;}catch(e){document.documentElement.dataset.theme="indigo";}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="pl"
      suppressHydrationWarning
      className={`${inter.variable} ${poppins.variable}`}
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
