"use client";

import { WorkBoard } from "@/components/work-board/WorkBoard";
import type { HrConfig } from "@/lib/api/hr";

/**
 * Tablica spraw administracja@ (makieta 19.10.2026) — od 22.10.2026 to
 * wspólna tablica pracy (`components/work-board/WorkBoard.tsx`) w zakresie
 * „Sprawy”: wszystkie dzisiejsze elementy zostają, osoba z dostępem do opieki
 * widzi też karty opieki, „Moi podopieczni” i kropkę zdrowia.
 */
export function CasesBoard({ config }: { config: HrConfig }) {
  return <WorkBoard scope="cases" config={config} />;
}
