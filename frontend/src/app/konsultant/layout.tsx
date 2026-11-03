import type { Metadata } from "next";

/**
 * Strefa konsultanta — bez powłoki aplikacji i bez konta NEXUSA (link z maila).
 * Ten sam wzór co `/protocol/{token}`. Publiczne wejście, ale nie do wyszukiwarek.
 */
export const metadata: Metadata = {
  title: "Strefa konsultanta",
  robots: { index: false, follow: false },
};

export default function ConsultantPortalLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-dvh bg-background text-foreground">{children}</div>;
}
