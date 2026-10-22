// Zakładka „Klienci” w /care (decyzja 9 z 22.10.2026) — filtry, kolejność
// i teksty komórek bez Reacta, z testami.

import type { CareClientRow } from "@/lib/api/care";
import { shortPersonName } from "@/lib/candidate-followup";
import { formatDayMonthPl } from "@/lib/date-pl";
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

/** „6 · 4 dobrze · 1 uwaga · 1 ryzyko” (makieta P4); bez kręgu D11 — sama liczba. */
export function healthCountsText(consultants: number, health: CareClientRow["health"]): string {
  if (!health) return String(consultants);
  const parts = [
    health.ok ? `${health.ok} dobrze` : null,
    health.watch ? `${health.watch} uwaga` : null,
    health.risk ? `${health.risk} ryzyko` : null,
  ].filter(Boolean);
  return [String(consultants), ...parts].join(" · ");
}

/**
 * Pod nazwą klienta: „DL Kamil T. · opiekun domyślny Natalia O.”. Bez DL
 * i bez domyślnego opiekuna konsultanci nie mają nikogo w łańcuchu —
 * „DL — · bez domyślnego opiekuna”.
 */
export function leadsText(row: Pick<CareClientRow, "delivery_leads" | "default_owner_name">): string {
  const leads = row.delivery_leads.map((name) => shortPersonName(name)).filter(Boolean);
  const parts = [`DL ${leads.length ? leads.join(", ") : "—"}`];
  if (row.default_owner_name) parts.push(`opiekun domyślny ${shortPersonName(row.default_owner_name)}`);
  else if (!leads.length) parts.push("bez domyślnego opiekuna");
  return parts.join(" · ");
}

/**
 * Pod „x z n” menedżerów: „3 menedżerów · drzewo pełne”, „2 pewne propozycje
 * do zatwierdzenia”, „bez propozycji automatu” (ktoś bez menedżera i automat
 * nikogo pewnego nie wskazał).
 */
export function managersSubline(
  row: Pick<CareClientRow, "managers_known" | "structure_open" | "proposals_certain" | "tree_complete">,
): string | null {
  const managers =
    row.managers_known > 1 ? countPl(row.managers_known, "menedżer", "menedżerów", "menedżerów") : null;
  if (row.tree_complete) return [managers, "drzewo pełne"].filter(Boolean).join(" · ");
  const proposals = row.proposals_certain ?? 0;
  if (proposals) {
    return `${countPl(proposals, "pewna propozycja", "pewne propozycje", "pewnych propozycji")} do zatwierdzenia`;
  }
  if (row.structure_open > 0) return "bez propozycji automatu";
  return row.managers_known ? [managers, "brak „Podlega pod”"].filter(Boolean).join(" · ") : null;
}

/** „ostatnia 21.07” albo `null` (komórka pokazuje „brak”). */
export function lastFeedbackText(lastOn: string | null): string | null {
  return lastOn ? `ostatnia ${formatDayMonthPl(lastOn)}` : null;
}

/** „1 prośba czeka od 19.10”, „2 prośby czekają od …”. */
export function pendingFeedbackText(count: number, since: string | null | undefined): string | null {
  if (!count) return null;
  const head =
    count === 1
      ? "1 prośba czeka"
      : countPl(count, "prośba czeka", "prośby czekają", "próśb czeka");
  return since ? `${head} od ${formatDayMonthPl(since)}` : head;
}

/** Mapa starsza niż tyle miesięcy to „stara” (makieta P4: „stara · 14 mies.”). */
export const MAP_FRESH_MONTHS = 6;

/** Pełne miesiące między dwiema datami ISO (RRRR-MM-DD). */
export function monthsBetween(fromIso: string, toIso: string): number {
  const [fy, fm, fd] = fromIso.slice(0, 10).split("-").map(Number);
  const [ty, tm, td] = toIso.slice(0, 10).split("-").map(Number);
  return Math.max(0, (ty - fy) * 12 + (tm - fm) - (td < fd ? 1 : 0));
}

/** „świeża · 08.10”, „stara · 14 mies.”, „brak źródeł”. */
export function mapFreshnessText(lastSourceOn: string | null, today: string): string {
  if (!lastSourceOn) return "brak źródeł";
  const months = monthsBetween(lastSourceOn, today);
  return months >= MAP_FRESH_MONTHS
    ? `stara · ${months} mies.`
    : `świeża · ${formatDayMonthPl(lastSourceOn)}`;
}

export function gapsText(gaps: number | null): string | null {
  if (gaps == null) return null;
  return gaps ? `${countPl(gaps, "luka", "luki", "luk")} do dopytania` : "bez luk";
}

/** Kończący w 60 dni pokazani z nazwiska; reszta jako „+n”. */
export const ENDING_SHOWN = 3;

/** „Paweł M. 22.11” · „Bartosz T. 31.12” (najwyżej trzy, potem „+n”). */
export function endingNames(items: CareClientRow["ending_60"]): {
  shown: { contractId: number; label: string; name: string }[];
  more: number;
} {
  return {
    shown: items.slice(0, ENDING_SHOWN).map((item) => ({
      contractId: item.contract_id,
      name: item.name,
      label: `${shortPersonName(item.name)} ${formatDayMonthPl(item.end_on)}`,
    })),
    more: Math.max(0, items.length - ENDING_SHOWN),
  };
}

export function openJobsText(count: number): string | null {
  return count ? countPl(count, "otwarta rekrutacja", "otwarte rekrutacje", "otwartych rekrutacji") : null;
}
