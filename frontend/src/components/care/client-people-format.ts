// Pomocnicze funkcje zakładki „Struktura u klienta” — bez Reacta, do testów.

import type { PersonRef } from "@/lib/api/care";
import {
  REASON_LABELS,
  formatAverage,
  type ClientOrg,
  type FeedbackReason,
  type LastFeedback,
  type OrgConsultant,
  type OrgPerson,
} from "@/lib/api/client-people";
import { formatIsoDatePl } from "@/lib/date-pl";

/** Wszystkie osoby klienta z drzewa (kolejność działów i wcięć). */
export function orgPeople(org: ClientOrg): OrgPerson[] {
  return org.departments.flatMap((department) => department.people);
}

/** Podwładni osoby — bezpośrednio i pośrednio (po polu „Podlega pod”). */
export function descendantIds(people: OrgPerson[], personId: number): Set<number> {
  const children = new Map<number, number[]>();
  for (const person of people) {
    const managerId = person.reports_to?.id;
    if (managerId == null) continue;
    children.set(managerId, [...(children.get(managerId) ?? []), person.id]);
  }
  const out = new Set<number>();
  const stack = [...(children.get(personId) ?? [])];
  while (stack.length) {
    const next = stack.pop() as number;
    if (out.has(next) || next === personId) continue;
    out.add(next);
    stack.push(...(children.get(next) ?? []));
  }
  return out;
}

/**
 * Kandydaci na „Podlega pod”: wszyscy poza samą osobą i jej podwładnymi —
 * wybór podwładnego zamknąłby pętlę (serwer i tak odmówi 422).
 */
export function managerOptions(people: OrgPerson[], person: OrgPerson): PersonRef[] {
  const blocked = descendantIds(people, person.id);
  blocked.add(person.id);
  return people
    .filter((candidate) => !blocked.has(candidate.id))
    .map((candidate) => ({ id: candidate.id, name: candidate.name }))
    .sort((a, b) => a.name.localeCompare(b.name, "pl"));
}

/** „zamówienie do 30.11.2026” / „umowa do …” / „bez daty końca”. */
export function endLabel(consultant: Pick<OrgConsultant, "end_date" | "end_source">): string {
  if (!consultant.end_date) return "bez daty końca";
  const kind = consultant.end_source === "contract" ? "umowa" : "zamówienie";
  return `${kind} do ${formatIsoDatePl(consultant.end_date)}`;
}

/** „opinia 12.08.2026 · 4 / 5” albo „bez opinii”. */
export function feedbackLabel(last: LastFeedback | null | undefined): string {
  if (!last) return "bez opinii";
  return `opinia ${formatIsoDatePl(last.held_on)} · ${formatAverage(last.average)}`;
}

export function reasonsLabel(reasons: FeedbackReason[]): string {
  return reasons.map((reason) => REASON_LABELS[reason]).join(" · ");
}
