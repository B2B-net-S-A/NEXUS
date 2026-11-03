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
 * (`entry_autofill.known`, serwer): najpierw nowi w bazie od progu (03.11.2026,
 * `entry_autofill.fresh_first`), potem pozostali bez uwag, potem z ostrzeżeniem
 * o budżecie albo biurze, na końcu z brakiem krytycznej. Procent na karcie się
 * nie zmienia. Zasady: docs/claude/rekrutacja-tablica/kolejka-w-nowych.md.
 */

export const CALL_FIRST_COUNT = 5;

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
    /** Nowa w bazie, od progu, bez uwag — liczy serwer (`has_fresh_first`). */
    fresh_first?: boolean;
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
  if (item.entry_autofill?.cautions?.length) return 1;
  return item.entry_autofill?.fresh_first ? -1 : 0;
}

export function orderNewColumn<T extends QueueItem>(
  items: readonly T[],
  criticalGaps?: ReadonlyMap<number, string[]>,
): { items: T[]; ranks: Map<number, number>; total: number; freshFirst: boolean } {
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
  const ranks = new Map<number, number>();
  queue.forEach(({ item }, index) => ranks.set(item.id, index + 1));
  return {
    items: [...team, ...queue.map(({ item }) => item)],
    ranks,
    total: queue.length,
    freshFirst: queue.some(({ tier: t }) => t < 0),
  };
}

export function newColumnSection(rank: number | undefined): NewColumnSection {
  if (rank == null) return "team";
  return rank <= CALL_FIRST_COUNT ? "call_first" : "rest";
}
