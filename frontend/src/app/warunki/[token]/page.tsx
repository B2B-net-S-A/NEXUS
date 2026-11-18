import type { Metadata } from "next";

import { TermsPage } from "@/components/candidate-terms/TermsPage";

/**
 * „Twoje warunki” — link z maila „Dziękujemy za zgłoszenie” (17.11.2026).
 * Publiczna trasa (`PUBLIC_PATHS` w middleware), bez indeksowania.
 * `?wypis=1` = ekran „Nie chcę dostawać takich pytań”.
 */
export const metadata: Metadata = {
  title: "Twoje warunki — B2B Network",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default async function WarunkiPage({
  params,
  searchParams,
}: {
  params: Promise<{ token: string }>;
  searchParams: Promise<{ wypis?: string }>;
}) {
  const { token } = await params;
  const { wypis } = await searchParams;
  return <TermsPage token={token} optOut={wypis === "1"} />;
}
