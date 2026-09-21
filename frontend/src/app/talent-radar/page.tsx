"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";
import { useAuthStore } from "@/store/auth";
import { hasCapability } from "@/lib/capabilities";
import { candidatesModeHref } from "@/lib/candidates-mode";

/**
 * Dostęp: KAŻDA zalogowana rola (decyzja produktowa Artura 19.08).
 *
 * Od 21.09.2026 Talent Radar to tryb „Z treści requestu" ekranu „Kandydaci".
 * Kto ma dostęp do kandydatów, jest tam przekierowywany (także z linków
 * w powiadomieniach). Rola BEZ `nav.candidates` (middleware nie wpuszcza jej
 * na `/candidates`) dalej dostaje radar tutaj — decyzja z 19.08 zostaje.
 *
 * Ta strona CELOWO nie ma żadnej bramki rolowej. Lustrzane miejsca tej
 * decyzji: backend (oba endpointy radaru na `CurrentUser`), middleware
 * (brak wpisu `/talent-radar` = sam login wymagany, deny-by-default)
 * i `nav.talent_radar = ALL_ROLES` w `lib/capabilities.ts`.
 * Nie przywracaj bramki tutaj bez zmiany wszystkich luster naraz.
 */
export default function TalentRadarPage() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const moveToCandidates = !!user && hasCapability(user, "nav.candidates");

  useEffect(() => {
    if (moveToCandidates) router.replace(candidatesModeHref("request"));
  }, [moveToCandidates, router]);

  if (!user || moveToCandidates) return null;
  return <TalentRadarWorkspace />;
}
