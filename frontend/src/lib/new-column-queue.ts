/**
 * Kolejka w kolumnie „Nowi” (decyzja Artura z 02.11.2026, makiety:
 * https://claude.ai/artifact/8x6AxqnTihmecy2uw3Dhoh). Serwer układa karty od
 * najmłodszego wejścia, a silnik dopełniania dodaje najlepszych jako pierwszych,
 * więc w każdej paczce kolejność wychodziła odwrotna: najlepsza osoba stała
 * średnio na 16. miejscu (korelacja z wynikiem −0,80 w 166 rekrutacjach).
 *
 * Osoby dodane przez zespół i karty od systemu, które ktoś już wziął, zostają
 * na górze od najmłodszego (decyzja z 16.10.2026). Pod nimi czekające karty od
 * systemu od najwyższego wyniku powiększonego o punkty „znamy tę osobę”
 * (`entry_autofill.known`, serwer): najpierw bez uwag, potem z ostrzeżeniem
 * o budżecie albo biurze, na końcu z brakiem krytycznej. Procent na karcie się
 * nie zmienia. Co 5. miejsce wśród osób bez uwag należy do najlepszej osoby bez
 * procesu (`entry_autofill.fresh`, decyzja z 03.11.2026), ta sama zasada co
 * `with_fresh_slots` na serwerze. Zasady: docs/claude/rekrutacja-tablica/kolejka-w-nowych.md.
 */

export const CALL_FIRST_COUNT = 5;
export const FRESH_EVERY = 5;

export type KnownFacts = {
  points: number;
  client_points: number;
  note_points: number;
  verified_at_client: number;
  last_note_days: number | null;
};

type QueueItem = {
  id: number;
  candidate_id: number;
  entry_source?: string | null;
  claim_user_id?: number | null;
  entry_autofill?: {
    score: number;
    decided: boolean;
    cautions?: unknown[];
    known?: KnownFacts | null;
    fresh?: boolean;
  } | null;
};

function queueValue(item: QueueItem): number {
  return (item.entry_autofill?.score ?? 0) + (item.entry_autofill?.known?.points ?? 0);
}

export function daysAgoText(days: number): string {
  if (days <= 0) return "dziś";
  return days === 1 ? "wczoraj" : `${days} dni temu`;
}

/** Krótkie powody na karcie „Zadzwoń najpierw”. */
export function knownFactLabels(known: KnownFacts | null | undefined): string[] {
  if (!known) return [];
  const labels: string[] = [];
  if (known.client_points > 0) labels.push(`U klienta · ${known.verified_at_client}×`);
  if (known.note_points > 0 && known.last_note_days != null) {
    labels.push(`Notatka ${daysAgoText(known.last_note_days)}`);
  }
  return labels;
}

export type NewColumnSection = "team" | "call_first" | "rest";

/** Karta od systemu, której jeszcze nikt nie wziął. */
export function waitsInSystemQueue(item: QueueItem): boolean {
  return (
    item.entry_source === "system" &&
    item.entry_autofill != null &&
    !item.entry_autofill.decided &&
    item.claim_user_id == null
  );
}

function tier(item: QueueItem, criticalGaps: ReadonlyMap<number, string[]> | undefined): number {
  if (criticalGaps?.get(item.candidate_id)?.length) return 2;
  return item.entry_autofill?.cautions?.length ? 1 : 0;
}

/** Co `FRESH_EVERY`-te miejsce dla najlepszej osoby bez procesu; `slots` to ci, którzy przeskoczyli. */
function withFreshSlots<T extends QueueItem>(sorted: readonly T[]): { items: T[]; slots: Set<number> } {
  const waiting = sorted
    .filter((item) => item.entry_autofill?.fresh)
    .sort(
      (a, b) =>
        (b.entry_autofill?.score ?? 0) - (a.entry_autofill?.score ?? 0) || a.candidate_id - b.candidate_id,
    );
  const items: T[] = [];
  const slots = new Set<number>();
  const used = new Set<number>();
  while (items.length < sorted.length) {
    const natural = sorted.find((item) => !used.has(item.id)) as T;
    const fresh =
      (items.length + 1) % FRESH_EVERY === 0 ? waiting.find((item) => !used.has(item.id)) : undefined;
    const pick = fresh ?? natural;
    if (pick !== natural) slots.add(pick.id);
    items.push(pick);
    used.add(pick.id);
  }
  return { items, slots };
}

export function orderNewColumn<T extends QueueItem>(
  items: readonly T[],
  criticalGaps?: ReadonlyMap<number, string[]>,
): { items: T[]; ranks: Map<number, number>; total: number; freshSlots: Set<number> } {
  const team = items.filter((item) => !waitsInSystemQueue(item));
  const queue = items
    .filter(waitsInSystemQueue)
    .map((item) => ({ item, tier: tier(item, criticalGaps) }))
    .sort(
      (a, b) =>
        a.tier - b.tier ||
        queueValue(b.item) - queueValue(a.item) ||
        a.item.candidate_id - b.item.candidate_id,
    );
  const clean = withFreshSlots(queue.filter(({ tier }) => tier === 0).map(({ item }) => item));
  const ordered = [...clean.items, ...queue.filter(({ tier }) => tier !== 0).map(({ item }) => item)];
  const ranks = new Map<number, number>();
  ordered.forEach((item, index) => ranks.set(item.id, index + 1));
  return { items: [...team, ...ordered], ranks, total: ordered.length, freshSlots: clean.slots };
}

export function newColumnSection(rank: number | undefined): NewColumnSection {
  if (rank == null) return "team";
  return rank <= CALL_FIRST_COUNT ? "call_first" : "rest";
}
