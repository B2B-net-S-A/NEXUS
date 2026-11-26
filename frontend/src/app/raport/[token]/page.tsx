import type { Metadata } from "next";

import { ReportConditionsPage } from "@/components/competence-report/ReportConditionsPage";

/**
 * „Twoje warunki” — link z maila z raportem kompetencji (25.11.2026).
 * Publiczna trasa (`PUBLIC_PATHS` w middleware, bez shellu w `AppShellV2`),
 * bez indeksowania. `?wypis=1` = wypis z raportów.
 */
export const metadata: Metadata = {
  title: "Twoje warunki — B2Bnetwork",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default async function RaportPage({
  params,
  searchParams,
}: {
  params: Promise<{ token: string }>;
  searchParams: Promise<{ wypis?: string }>;
}) {
  const { token } = await params;
  const { wypis } = await searchParams;
  return <ReportConditionsPage token={token} optOut={wypis === "1"} />;
}
