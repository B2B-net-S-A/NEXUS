// „Zespół opiekunów” (22.10.2026, makieta P6) — tabela opiekunów z zaległymi
// rozmowami, zrobionymi w miesiącu i stanem portfela, liczona z tych samych
// odpowiedzi co „Konsultanci” i „Przydział” (bez nowego zapytania), oraz
// zwinięty opis ustawień przydziału. Bez Reacta, z testem.

import type { CareAssignment, CareAutoAssignment, ConsultantRow, OwnerLoad } from "@/lib/api/care";
import { shortPersonName } from "@/lib/candidate-followup";
import { formatDayMonthPl } from "@/lib/date-pl";

import { peopleText, talksText } from "../cadence-format";
import { healthTotals, type HealthTotals } from "../health-format";

/** Limit jednego zapisu (`MAX_BULK` w `care/assignment.py`) — więcej = 422 i nic się nie zapisuje. */
export const MAX_BULK_ASSIGN = 500;

export interface TeamRow {
  id: number;
  name: string;
  isDeliveryLead: boolean;
  isTcm: boolean;
  inPool: boolean;
  consultants: number;
  overdue: number;
  health: HealthTotals;
  /** Rozmowy w następnym miesiącu z rytmów (`OwnerLoad.conversations`); `null` — brak w przydziale. */
  conversations: number | null;
  overThreshold: boolean;
  /** Bieżący miesiąc: zapisane rozmowy z przewidzianych rytmami; `null` — serwer sprzed 22.10. */
  done: number | null;
  planned: number | null;
}

/**
 * Wiersz na opiekuna: podopieczni i zaległe z listy „Konsultanci” (faktyczny
 * opiekun z łańcucha), obciążenie i „zrobione” z „Przydziału”. Osoby z puli
 * i TCM bez podopiecznych też mają wiersz — do nich automat przypisze.
 * Kolejność: najwięcej zaległych, ryzyka, podopiecznych, potem nazwisko.
 */
export function teamRows(consultants: ConsultantRow[], owners: OwnerLoad[]): TeamRow[] {
  const byOwner = new Map<number, { name: string; rows: ConsultantRow[] }>();
  for (const row of consultants) {
    if (!row.owner) continue;
    const entry = byOwner.get(row.owner.id) ?? { name: row.owner.name, rows: [] };
    entry.rows.push(row);
    byOwner.set(row.owner.id, entry);
  }
  const loads = new Map(owners.map((owner) => [owner.id, owner]));
  const ids = new Set<number>([
    ...byOwner.keys(),
    ...owners.filter((o) => o.consultants > 0 || o.in_pool || o.is_tcm).map((o) => o.id),
  ]);
  const rows: TeamRow[] = [...ids].map((id) => {
    const entry = byOwner.get(id);
    const load = loads.get(id);
    const list = entry?.rows ?? [];
    return {
      id,
      name: entry?.name ?? load?.name ?? "—",
      isDeliveryLead: load?.is_delivery_lead ?? false,
      isTcm: load?.is_tcm ?? false,
      inPool: load?.in_pool ?? false,
      consultants: list.length || load?.consultants || 0,
      overdue: list.filter((row) => row.next_contact?.overdue).length,
      health: healthTotals(list),
      conversations: load ? load.conversations : null,
      overThreshold: load?.over_threshold ?? false,
      done: load?.done_this_month ?? null,
      planned: load?.planned_this_month ?? null,
    };
  });
  return rows.sort(
    (a, b) =>
      b.overdue - a.overdue ||
      b.health.risk - a.health.risk ||
      b.consultants - a.consultants ||
      a.name.localeCompare(b.name, "pl"),
  );
}

/** Konsultanci bez opiekuna w łańcuchu (lista „Konsultanci”). */
export function withoutOwner(consultants: ConsultantRow[]): number {
  return consultants.filter((row) => !row.owner).length;
}

/** Podpis pod opiekunem: „TCM · w puli”, „Delivery Lead · tylko swoi klienci”, „w puli · bez podopiecznych”. */
export function ownerRoleText(row: Pick<TeamRow, "isTcm" | "isDeliveryLead" | "inPool" | "consultants">): string {
  return [
    row.isTcm ? "TCM" : row.isDeliveryLead ? "Delivery Lead" : null,
    row.inPool ? "w puli" : null,
    row.isDeliveryLead && !row.isTcm && !row.inPool ? "tylko swoi klienci" : null,
    row.consultants === 0 ? "bez podopiecznych" : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** „21 rozmów — powyżej progu”. */
export function loadText(row: Pick<TeamRow, "conversations" | "overThreshold">): string | null {
  if (row.conversations == null) return null;
  return row.overThreshold ? `${talksText(row.conversations)} — powyżej progu` : talksText(row.conversations);
}

/** „9 z 11” albo `null` (nic nie przewidziane i nic nie zapisane). */
export function doneText(row: Pick<TeamRow, "done" | "planned">): string | null {
  if (row.done == null || row.planned == null) return null;
  if (!row.done && !row.planned) return null;
  return `${row.done} z ${row.planned}`;
}

/** „5 dobrze · 1 uwaga · 1 ryzyko” albo `null`. */
export function portfolioText(health: HealthTotals): string | null {
  const parts = [
    health.ok ? `${health.ok} dobrze` : null,
    health.watch ? `${health.watch} uwaga` : null,
    health.risk ? `${health.risk} ryzyko` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

const MONTHS_LOCATIVE = [
  "styczniu",
  "lutym",
  "marcu",
  "kwietniu",
  "maju",
  "czerwcu",
  "lipcu",
  "sierpniu",
  "wrześniu",
  "październiku",
  "listopadzie",
  "grudniu",
] as const;

/** „w listopadzie” z „2026-11-01”. */
export function inMonthPl(iso: string): string {
  const month = Number(iso.slice(5, 7));
  return `w ${MONTHS_LOCATIVE[month - 1] ?? "miesiącu"}`;
}

/** Zwinięte „Ustawienia przydziału” w jednej linii (makieta P6). */
export function settingsSummary(
  assignment: Pick<CareAssignment, "threshold" | "clients">,
  auto: Pick<CareAutoAssignment, "pool" | "config"> | null,
): string {
  const parts: string[] = [];
  if (auto) {
    const manager = auto.config.manager?.name ? shortPersonName(auto.config.manager.name) : null;
    parts.push(
      manager ? `pula (przełożony ${manager}): ${peopleText(auto.pool.length)}` : "pula: nie wskazano przełożonego",
    );
    parts.push(`„Nie przypisuj”: ${auto.config.excluded_user_ids.length}`);
  }
  const threshold = assignment.threshold.monthly_conversations;
  parts.push(threshold ? `próg: ${talksText(threshold)} / mies.` : "próg: brak");
  if (auto) {
    const on = auto.config.saved && auto.config.auto_new_contracts;
    parts.push(`nowy kontrakt → automat: ${on ? "włączony" : "wyłączony"}`);
  }
  const withDefault = assignment.clients.filter((client) => client.default_owner).length;
  parts.push(`domyślni opiekunowie klientów: ${withDefault} z ${assignment.clients.length}`);
  return parts.join(" · ");
}

/**
 * Pasek „bez opiekuna”: „2 konsultantów bez opiekuna (Klinika Testowa IT,
 * start 07.11)” — klienci (najwyżej dwóch) i najbliższy start z podglądu
 * automatu.
 */
export function orphansText(items: CareAutoAssignment["items"]): string | null {
  if (!items.length) return null;
  const clients = [...new Set(items.map((item) => item.client_name))];
  const starts = items
    .map((item) => item.start_date)
    .filter((value): value is string => Boolean(value))
    .sort();
  const detail = [
    clients.slice(0, 2).join(", ") + (clients.length > 2 ? ` i ${clients.length - 2} innych` : ""),
    starts.length ? `start ${formatDayMonthPl(starts[0])}` : null,
  ]
    .filter(Boolean)
    .join(", ");
  const who = items.length === 1 ? "1 konsultant" : `${items.length} konsultantów`;
  return `${who} bez opiekuna (${detail})`;
}

/** `/care?tab=consultants&owner=<id>` — „Konsultanci” jednego opiekuna. */
export function consultantsOfHref(ownerId: number | "none"): string {
  return `/care?tab=consultants&owner=${ownerId}`;
}
