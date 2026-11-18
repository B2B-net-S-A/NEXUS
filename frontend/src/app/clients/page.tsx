"use client";

import { Suspense, useEffect, useState } from "react";
import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";

/**
 * „Klienci" = jeden ekran z dwoma trybami: lista klientów (z przełącznikiem
 * „Moi / Wszyscy" — dawny „Panel klientów") i kluczowe relacje (dawne „Moje
 * relacje"). Patrz `lib/clients-workspace.ts`.
 *
 * Client-only gate — patrz komentarz w /contracts/page.tsx.
 */
export default function ClientsPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie klientów…</div>;
  }
  return (
    <Suspense
      fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie klientów…</div>}
    >
      <ClientsWorkspace />
    </Suspense>
  );
}

/**
 * Makieta 18.11.2026 („prościej”): moduł Klienci to jedna lista. Umowy,
 * raporty i relacje są w profilu klienta, a to, co wymaga uwagi (raport
 * miesiąca, relacja bez kontaktu, umowa kończąca się w 90 dni), widać
 * w wierszu klienta. Dawne adresy `?view=` otwierają tę samą listę.
 */
function ClientsWorkspace() {
  return <ClientsListV2 modeTabs={null} />;
}
