/**
 * Wybór terminu rozmowy z maila, `/t/{token}`. Dostęp daje sam link, bez konta.
 * Nie trafia do wyszukiwarek, a adres nie wychodzi w nagłówku Referer.
 */
import type { Metadata } from "next";

import { PublicBookingApp } from "@/components/v2/own-hiring/PublicBookingApp";

export const metadata: Metadata = {
  title: "Wybór terminu rozmowy",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

interface PageProps {
  params: Promise<{ token: string }>;
}

export default async function BookingPage({ params }: PageProps) {
  const { token } = await params;
  return <PublicBookingApp token={token} />;
}
