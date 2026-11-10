// Lejek Fabryki IT mierzony kontaktem: podpisy i sumy. Definicje (kto jest
// „po kontakcie”, kiedy etap rozjeżdża się z mapą) trzyma backend:
// services/sales/factories.py.

import type { DecisionMapEntry, Opportunity } from "@/lib/api/sales";
import type { FactoryAccount, FactoryQueuePerson, KnownCounts } from "@/lib/api/sales-factories";

import { DECISION_LEVELS } from "../decision-map-labels";
import { plural } from "../peoplePlural";

export interface FactorySummary {
  accounts: number;
  people: number;
  contacted: number;
  topTotal: number;
  topContacted: number;
}

/** Sumy dla kont widocznych na liście (po filtrach), nie dla całego lejka. */
export function summarizeAccounts(
  items: readonly Opportunity[],
  facts: ReadonlyMap<number, FactoryAccount>,
): FactorySummary {
  return items.reduce<FactorySummary>(
    (sum, item) => {
      const account = facts.get(item.id);
      if (!account) return { ...sum, accounts: sum.accounts + 1 };
      return {
        accounts: sum.accounts + 1,
        people: sum.people + account.map_total,
        contacted: sum.contacted + account.map_contacted,
        topTotal: sum.topTotal + account.top_total,
        topContacted: sum.topContacted + account.top_contacted,
      };
    },
    { accounts: 0, people: 0, contacted: 0, topTotal: 0, topContacted: 0 },
  );
}

export function peopleLabel(count: number): string {
  return `${count} ${plural(count, "osoba", "osoby", "osób")}`;
}

export function summaryLine(summary: FactorySummary): string {
  const accounts = `${summary.accounts} ${plural(summary.accounts, "konto", "konta", "kont")}`;
  if (summary.people === 0) return `${accounts} · mapy są puste`;
  const share = Math.round((summary.contacted / summary.people) * 100);
  return [
    accounts,
    `${peopleLabel(summary.people)} na mapach`,
    `po kontakcie ${summary.contacted} (${share}%)`,
    `poziom 1 i 2: ${summary.topContacted} z ${summary.topTotal}`,
  ].join(" · ");
}

/** Podpowiedź przy etapie, który mówi o kontakcie, gdy mapa go nie potwierdza. */
export function stageHint(account: FactoryAccount | undefined): string | null {
  if (!account?.stage_mismatch) return null;
  return account.map_total === 0 ? "mapa jest pusta" : "na mapie nikt po kontakcie";
}

export const STAGE_HINT_TITLE =
  "Etap mówi o kontakcie, a żadna osoba z mapy nie ma go za sobą. Popraw status osoby albo etap. Nic nie jest blokowane.";

export function levelLabel(person: DecisionMapEntry): string {
  const level = person.decision_level;
  if (!level) return "Bez poziomu";
  return `Poziom ${level} · ${DECISION_LEVELS[level - 1] ?? ""}`.replace(/ · $/, "");
}

/** Którymi kanałami da się dotrzeć do osoby; sam spis, bez klikalnych adresów. */
export function channelsLabel(person: DecisionMapEntry): string {
  const channels = [
    person.phone ? "telefon" : null,
    person.email ? "e-mail" : null,
    person.linkedin_url ? "LinkedIn" : null,
  ].filter(Boolean);
  return channels.length > 0 ? channels.join(" · ") : "brak danych kontaktowych";
}

/** „Znamy teraz 49 · kiedyś 114”; `undefined` to liczniki, których jeszcze nie ma. */
export function knownLabel(counts: KnownCounts | undefined): string | null {
  if (!counts) return null;
  if (counts.current === 0 && counts.past === 0) return "nikogo z bazy tam nie znamy";
  return `z bazy pracuje tam teraz ${counts.current} · kiedyś ${counts.past}`;
}

export function matchesSearch(row: FactoryQueuePerson, query: string): boolean {
  const needle = query.trim().toLocaleLowerCase("pl");
  if (!needle) return true;
  return [row.company.name, row.person.name, row.person.role_in_company]
    .filter((value): value is string => Boolean(value))
    .some((value) => value.toLocaleLowerCase("pl").includes(needle));
}
