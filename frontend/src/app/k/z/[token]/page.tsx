/**
 * Panel klienta dla zespołu, `/k/z/{token}?p={klucz stanowiska}`
 * (`docs/claude/klienci/zespol-dla-klienta.md`). Dostęp daje sam link, bez
 * konta: strona stoi poza powłoką aplikacji (prefiks `/k/`) i nie wysyła tokenu
 * użytkownika. Nie trafia do wyszukiwarek, a adres nie wychodzi w nagłówku Referer.
 */
import type { Metadata } from "next";

import { ClientTeamPanelApp } from "@/components/v2/team-request/ClientTeamPanelApp";

export const metadata: Metadata = {
  title: "Zespół od B2B Network",
  robots: { index: false, follow: false, nocache: true },
  referrer: "no-referrer",
};

interface PageProps {
  params: Promise<{ token: string }>;
  searchParams: Promise<{ p?: string | string[] }>;
}

export default async function ClientTeamPanelPage({ params, searchParams }: PageProps) {
  const { token } = await params;
  const { p } = await searchParams;
  return <ClientTeamPanelApp token={token} initialPosition={typeof p === "string" ? p : null} />;
}
