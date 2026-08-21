"use client";

import { TalentRadarWorkspace } from "@/components/talent-radar/TalentRadarWorkspace";

/**
 * Dostęp: KAŻDA zalogowana rola (decyzja produktowa Artura 19.08).
 *
 * Ta strona CELOWO nie ma żadnej bramki rolowej. Lustrzane miejsca tej
 * decyzji: backend (oba endpointy radaru na `CurrentUser`), middleware
 * (brak wpisu `/talent-radar` = sam login wymagany, deny-by-default),
 * sidebar (pozycja bez `roles`) i `nav.talent_radar = ALL_ROLES`
 * w `lib/capabilities.ts`.
 *
 * Historia: do 19.08 stał tu `RequireRole` z listą ról require_candidate_write
 * — PIĄTA kopia tej listy, która przeżyła otwarcie radaru w #1212 i dalej
 * pokazywała „Brak uprawnień" rolom spoza starej piątki. Nie przywracaj
 * bramki tutaj bez zmiany wszystkich luster naraz.
 */
export default function TalentRadarPage() {
  return <TalentRadarWorkspace />;
}
