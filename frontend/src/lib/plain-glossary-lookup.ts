/**
 * Słowniczek „po ludzku” pod chipami technologii w Briefie (04.10.2026).
 *
 * Hasło słowniczka ma `display_name` = nazwa ze stacku profilu (serwer bierze
 * ją wprost z `stack.must`/`stack.nice`, `job_brief.py`), a chipy Briefu
 * rysują się z tych samych nazw. Klucza `term_key` (forma kanoniczna) front
 * policzyć nie umie, więc łączymy po nazwie bez wielkości liter i białych
 * znaków na brzegach. Hasło bez opisu (w researchu, nieudane) nie daje dymka —
 * dymek „Szukam opisu…” na chipie byłby szumem.
 */

import type { GlossaryTerm } from "@/lib/api/plainKnowledge";

export function glossaryKey(name: string): string {
  return name.trim().toLocaleLowerCase("pl-PL");
}

export function buildGlossaryLookup(
  terms: readonly GlossaryTerm[] | null | undefined,
): Map<string, GlossaryTerm> {
  const map = new Map<string, GlossaryTerm>();
  for (const term of terms ?? []) {
    if (term.status !== "ready" || !term.summary?.trim()) continue;
    const key = glossaryKey(term.display_name);
    if (key && !map.has(key)) map.set(key, term);
  }
  return map;
}

/** Liczba haseł z opisem — licznik przy zakładce „Technologie po ludzku”. */
export function readyGlossaryCount(terms: readonly GlossaryTerm[] | null | undefined): number {
  return (terms ?? []).filter((t) => t.status === "ready" && t.summary?.trim()).length;
}
