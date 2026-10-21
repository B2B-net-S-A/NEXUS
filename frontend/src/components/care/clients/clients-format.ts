// Zakładka „Klienci” w /care (decyzja 9 z 22.10.2026) — filtry, kolejność
// i teksty komórek bez Reacta, z testami.

import type { CareClientRow } from "@/lib/api/care";
import { countPl } from "@/lib/plural-pl";

export type ClientFilter = "all" | "knowledge" | "demand" | "risk" | "ending";

export const CLIENT_FILTERS: { value: ClientFilter; label: string }[] = [
  { value: "all", label: "Wszyscy" },
  { value: "knowledge", label: "Wiedza do uzupełnienia" },
  { value: "demand", label: "Z popytem" },
  { value: "risk", label: "Z ryzykiem" },
  { value: "ending", label: "Kończą w 60 dni" },
];

/** Wiedza do uzupełnienia: konsultanci bez menedżera, luki mapy albo mapa bez źródła. */
export function needsKnowledge(row: CareClientRow): boolean {
  if (row.structure_open > 0) return true;
  if (!row.map) return false;
  return (row.map.gaps ?? 0) > 0 || !row.map.last_source_on;
}

/** Popyt: sygnał „klient zatrudnia” z rozmów albo technologie z popytu. */
export function hasDemand(row: CareClientRow): boolean {
  return row.demand.hiring_signal || row.demand.skills.length > 0;
}

export function matchesClientFilter(row: CareClientRow, filter: ClientFilter): boolean {
  switch (filter) {
    case "all":
      return true;
    case "knowledge":
      return needsKnowledge(row);
    case "demand":
      return hasDemand(row);
    case "risk":
      return (row.health?.risk ?? 0) > 0;
    case "ending":
      return row.ending_60.length > 0;
  }
}

export function clientFilterCounts(rows: CareClientRow[]): Record<ClientFilter, number> {
  const counts = { all: 0, knowledge: 0, demand: 0, risk: 0, ending: 0 } as Record<ClientFilter, number>;
  for (const row of rows) {
    for (const { value } of CLIENT_FILTERS) {
      if (matchesClientFilter(row, value)) counts[value] += 1;
    }
  }
  return counts;
}

/** Najpierw ryzyko (najwięcej osób), potem uwaga, potem nazwa. */
export function sortClients(rows: CareClientRow[]): CareClientRow[] {
  return rows.slice().sort((a, b) => {
    const risk = (b.health?.risk ?? 0) - (a.health?.risk ?? 0);
    if (risk) return risk;
    const watch = (b.health?.watch ?? 0) - (a.health?.watch ?? 0);
    if (watch) return watch;
    return a.name.localeCompare(b.name, "pl");
  });
}

/**
 * Menedżerowie u klienta „x z n”: ilu naszych konsultantów ma wskazanego
 * menedżera u klienta (n − „do uzupełnienia”) z n.
 */
export function managersText(row: CareClientRow): string {
  const known = Math.max(0, row.consultants - row.structure_open);
  return `${known} z ${row.consultants}`;
}

/** „2 ryzyko · 1 uwaga” — bez „dobrze” (to pasek). */
export function healthCountsText(health: CareClientRow["health"]): string | null {
  if (!health) return null;
  const parts = [
    health.risk ? `${health.risk} ryzyko` : null,
    health.watch ? `${health.watch} uwaga` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "wszyscy dobrze";
}

export function gapsText(gaps: number | null): string | null {
  if (gaps == null) return null;
  return gaps ? countPl(gaps, "luka", "luki", "luk") : "bez luk";
}

export function openJobsText(count: number): string | null {
  return count ? countPl(count, "otwarta rekrutacja", "otwarte rekrutacje", "otwartych rekrutacji") : null;
}
