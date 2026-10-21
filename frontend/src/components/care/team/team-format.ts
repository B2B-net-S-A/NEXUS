// „Zespół opiekunów” (22.10.2026) — tabela opiekunów z zaległymi rozmowami
// i stanem portfela, liczona z tych samych odpowiedzi co „Konsultanci”
// i „Przydział” (bez nowego zapytania). Bez Reacta, z testem.

import type { ConsultantRow, OwnerLoad } from "@/lib/api/care";

import { healthTotals, type HealthTotals } from "../health-format";

export interface TeamRow {
  id: number;
  name: string;
  isDeliveryLead: boolean;
  consultants: number;
  overdue: number;
  health: HealthTotals;
  /** Rozmowy w następnym miesiącu z rytmów (`OwnerLoad.conversations`); `null` — brak w przydziale. */
  conversations: number | null;
  overThreshold: boolean;
}

/**
 * Wiersz na opiekuna: podopieczni i zaległe z listy „Konsultanci” (faktyczny
 * opiekun z łańcucha), obciążenie z „Przydziału”. Kolejność: najwięcej
 * zaległych, potem ryzyka, potem nazwisko.
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
  const ids = new Set<number>([...byOwner.keys(), ...owners.filter((o) => o.consultants > 0).map((o) => o.id)]);
  const rows: TeamRow[] = [...ids].map((id) => {
    const entry = byOwner.get(id);
    const load = loads.get(id);
    const list = entry?.rows ?? [];
    return {
      id,
      name: entry?.name ?? load?.name ?? "—",
      isDeliveryLead: load?.is_delivery_lead ?? false,
      consultants: list.length || load?.consultants || 0,
      overdue: list.filter((row) => row.next_contact?.overdue).length,
      health: healthTotals(list),
      conversations: load ? load.conversations : null,
      overThreshold: load?.over_threshold ?? false,
    };
  });
  return rows.sort(
    (a, b) =>
      b.overdue - a.overdue || b.health.risk - a.health.risk || a.name.localeCompare(b.name, "pl"),
  );
}

/** Konsultanci bez opiekuna w łańcuchu (lista „Konsultanci”). */
export function withoutOwner(consultants: ConsultantRow[]): number {
  return consultants.filter((row) => !row.owner).length;
}
