/**
 * Panel klienta pod linkiem z CV, `/k/{token}?c={public_id}`. Dostęp daje sam
 * link, bez konta: strona stoi poza powłoką aplikacji i nie wysyła tokenu
 * użytkownika. Nie trafia do wyszukiwarek, a adres nie wychodzi w nagłówku Referer.
 */
import type { Metadata } from "next";

import { ClientPanelApp } from "@/components/v2/client-panel/ClientPanelApp";

export const metadata: Metadata = {
  title: "Panel klienta B2B Network",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

interface PageProps {
  params: Promise<{ token: string }>;
  searchParams: Promise<{ c?: string | string[] }>;
}

export default async function ClientPanelPage({ params, searchParams }: PageProps) {
  const { token } = await params;
  const { c } = await searchParams;
  return <ClientPanelApp token={token} initialPublicId={typeof c === "string" ? c : null} />;
}
