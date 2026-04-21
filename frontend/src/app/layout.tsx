import type { Metadata } from "next";
import { Inter, Poppins } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { QueryProvider } from "@/components/QueryProvider";
import { AppShell } from "@/components/AppShell";
import { AppShellV2 } from "@/components/v2/shell/AppShellV2";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ToastProvider } from "@/components/Toast";
import { UiFlagUrlSync } from "@/components/UiFlagUrlSync";
import { TooltipProvider } from "@/components/ui/tooltip";
import { readUiFlagFromCookies } from "@/lib/ui-flag";

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

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const ui = readUiFlagFromCookies(cookieStore);

  return (
    <html
      lang="pl"
      data-ui={ui}
      suppressHydrationWarning
      className={`${inter.variable} ${poppins.variable}`}
    >
      <body className="bg-gray-50 dark:bg-gray-950 text-gray-900 dark:text-gray-100 font-sans">
        <UiFlagUrlSync />
        <QueryProvider>
          <ThemeProvider>
            <ToastProvider>
              <TooltipProvider delayDuration={200} skipDelayDuration={100}>
                {ui === "v2" ? (
                  <AppShellV2>{children}</AppShellV2>
                ) : (
                  <AppShell>{children}</AppShell>
                )}
              </TooltipProvider>
            </ToastProvider>
          </ThemeProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
