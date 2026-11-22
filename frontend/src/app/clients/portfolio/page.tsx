"use client";

import { Suspense, useEffect, useState } from "react";
import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";

/**
 * „Porządki portfela” — dawna lista „Klienci” w trzech zakładkach portfela
 * (zakresy umów ramowych, „Przenieś”, ręczne daty umów, czyszczenie
 * nieaktywnych). Od 19.11.2026 lista „Klienci” liczy stan współpracy sama,
 * a tu zostaje narzędzie administratora portfela (link pod listą).
 */
export default function ClientPortfolioPage() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  if (!mounted) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie portfela…</div>;
  }
  return (
    <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Ładowanie portfela…</div>}>
      <ClientsListV2 modeTabs={null} variant="portfolio" />
    </Suspense>
  );
}
