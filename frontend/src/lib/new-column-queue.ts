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
 * nie zmienia. Co 5. miejsce wśród osób bez uwag należy do najlepszej osoby bez
 * procesu (`entry_autofill.fresh`, decyzja z 03.11.2026), ta sama zasada co
 * `with_fresh_slots` na serwerze. Zasady: docs/claude/rekrutacja-tablica/kolejka-w-nowych.md.
 *
 * Zgłoszenia (06.11.2026, makiety https://claude.ai/artifact/JMTL5qwBym7Twd2dU1uYsb):
 * osoba, która sama aplikowała (`entry_source = application`: strona kariery,
 * formularz JustJoin.IT), stoi na samej górze, jeśli ma wszystkie „musi mieć”.
 * Z brakiem krytycznej idzie na koniec, do grupy „Aplikowali, brak »musi mieć«”,
 * którą tablica domyślnie zwija. Pomiar 06.11: 32 z 81 aplikujących z JJIT
 * nie miało którejś krytycznej, a 12 z nich miało wynik ≥ 65, dlatego
 * odkładamy, nie odrzucamy.
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
  /** Wynik „Sprawdź w CV” / przeglądu AI — „pasuje” wyciąga z grupy zwiniętej. */
  entry_ai_screening?: { verdict?: string | null } | null;
  entry_autofill?: {
    score: number;
    decided: boolean;
    cautions?: unknown[];
    known?: KnownFacts | null;
    /** Nowa w bazie, od progu, bez uwag — liczy serwer (`has_fresh_first`). */
    fresh_first?: boolean;
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

export type NewColumnSection = "applied" | "team" | "call_first" | "rest" | "applied_gap";

/** Osoba sama się zgłosiła (strona kariery, formularz portalu). */
export function isApplication(item: QueueItem): boolean {
  return item.entry_source === "application";
}

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

/**
 * Co `FRESH_EVERY`-te miejsce dla najlepszej osoby bez procesu; `slots` to ci, którzy
 * przeskoczyli. `start` = karty przed tą listą (nowi w bazie): miejsce liczy się w całej kolejce.
 */
function withFreshSlots<T extends QueueItem>(sorted: readonly T[], start = 0): { items: T[]; slots: Set<number> } {
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
      (start + items.length + 1) % FRESH_EVERY === 0 ? waiting.find((item) => !used.has(item.id)) : undefined;
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
): {
  items: T[];
  ranks: Map<number, number>;
  total: number;
  freshFirst: boolean;
  freshSlots: Set<number>;
  sections: Map<number, NewColumnSection>;
  appliedGapIds: Set<number>;
} {
  // „AI: pasuje” (przegląd albo „Sprawdź w CV”) wygrywa z brakiem słowa w CV.
  const hasGap = (item: T) =>
    Boolean(criticalGaps?.get(item.candidate_id)?.length) && item.entry_ai_screening?.verdict !== "fits";
  const outsideQueue = items.filter((item) => !waitsInSystemQueue(item));
  const applied = outsideQueue.filter((item) => isApplication(item) && !hasGap(item));
  const appliedGap = outsideQueue.filter((item) => isApplication(item) && hasGap(item));
  const team = outsideQueue.filter((item) => !isApplication(item));
  const queue = items
    .filter(waitsInSystemQueue)
    .map((item) => ({ item, tier: tier(item, criticalGaps) }))
    .sort(
      (a, b) =>
        a.tier - b.tier ||
        queueValue(b.item) - queueValue(a.item) ||
        a.item.candidate_id - b.item.candidate_id,
    );
  const first = queue.filter(({ tier }) => tier < 0).map(({ item }) => item);
  const clean = withFreshSlots(queue.filter(({ tier }) => tier === 0).map(({ item }) => item), first.length);
  const ordered = [...first, ...clean.items, ...queue.filter(({ tier }) => tier > 0).map(({ item }) => item)];
  const ranks = new Map<number, number>();
  ordered.forEach((item, index) => ranks.set(item.id, index + 1));
  const sections = new Map<number, NewColumnSection>();
  applied.forEach((item) => sections.set(item.id, "applied"));
  team.forEach((item) => sections.set(item.id, "team"));
  ordered.forEach((item, index) => sections.set(item.id, newColumnSection(index + 1)));
  appliedGap.forEach((item) => sections.set(item.id, "applied_gap"));
  return {
    items: [...applied, ...team, ...ordered, ...appliedGap],
    ranks,
    total: ordered.length,
    freshFirst: first.length > 0,
    freshSlots: clean.slots,
    sections,
    appliedGapIds: new Set(appliedGap.map((item) => item.id)),
  };
}

export function newColumnSection(rank: number | undefined): NewColumnSection {
  if (rank == null) return "team";
  return rank <= CALL_FIRST_COUNT ? "call_first" : "rest";
}
