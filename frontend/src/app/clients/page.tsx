"use client";

import { Suspense, useEffect, useState } from "react";
import { ClientsList } from "@/components/clients/ClientsList";

/**
 * „Klienci” = jedna lista, jeden wiersz na klienta, stan współpracy liczony
 * z faktów (makieta 19.11.2026, wariant A). Umowy, raporty i relacje są
 * w profilu klienta, a to, co wymaga uwagi, widać w wierszu. Dawne adresy
 * (`?category=`, `?view=`) otwierają tę samą listę. Zakładki portfela
 * i ręczne ustawienia: „Porządki portfela” (`/clients/portfolio`).
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
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie klientów…</div>}>
      <ClientsList />
    </Suspense>
  );
}
