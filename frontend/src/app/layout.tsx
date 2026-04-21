import type { Metadata } from "next";
import { Inter, Poppins } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";
import { QueryProvider } from "@/components/QueryProvider";
import { AppShell } from "@/components/AppShell";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ToastProvider } from "@/components/Toast";
import { UiFlagUrlSync } from "@/components/UiFlagUrlSync";
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
              {/* Phase 0: shell selector is wired, but both branches still render v1 AppShell.
                  Phase 2 flips the v2 branch to <AppShellV2>. */}
              {ui === "v2" ? (
                <AppShell>{children}</AppShell>
              ) : (
                <AppShell>{children}</AppShell>
              )}
            </ToastProvider>
          </ThemeProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
