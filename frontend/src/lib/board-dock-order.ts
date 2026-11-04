/**
 * Kolejność nawigatora doku „‹ N z M ›" na Tablicy — DOKŁADNIE ta, którą widać:
 * kolumny od lewej (złożone kolumny Tablicy, rozwinięci zamknięci, „Poza
 * szablonem"), karty od góry w kolejności renderu.
 *
 * Do 24.09.2026 dok liczył kolejność z surowych etapów szablonu, więc pierwsza
 * karta w „Nowi" miała „12 z 35", a „←" prowadziło do ostatniej karty kolumny.
 * Do 02.10.2026 pomijał karty przygaszone filtrami — pasek filtrów zniknął.
 * Od 14.10.2026 (D1) strzałki chodzą po JEDNEJ kolumnie — kolumnie otwartej
 * osoby, zawężonej filtrem „Kto dodał” (`board-added-by.ts`); Tablica podaje
 * tu tylko tę kolumnę. Zasady:
 * docs/claude/rekrutacja-tablica/nastepna-osoba-po-odrzuceniu.md („Kolejka w kolumnie…”).
 */

export function dockNavigationOrder<T extends { candidate_id: number }>(
  columns: ReadonlyArray<{ items: ReadonlyArray<T> }>,
): number[] {
  const order: number[] = [];
  const seen = new Set<number>();
  for (const col of columns) {
    for (const item of col.items) {
      if (seen.has(item.candidate_id)) continue;
      seen.add(item.candidate_id);
      order.push(item.candidate_id);
    }
  }
  return order;
}

/**
 * Kolumna kolejki po zmianie osoby w panelu (D1, 14.10.2026). Osoba z obecnej
 * kolejki (strzałki, przejście po odrzuceniu, „Wróć do kolejki”) — kolejka
 * zostaje. Osoba z innej kolumny Tablicy — kolejką staje się jej kolumna.
 * Osoba spoza kolumn Tablicy (zamknięta, „Pokaż”) — kolejka zostaje.
 */
export function queueColumnAfterOpen(
  previous: string | null,
  candidateId: number,
  queueOrder: readonly number[],
  columnOfCandidate: string | null,
): string | null {
  if (previous != null && queueOrder.includes(candidateId)) return previous;
  return columnOfCandidate ?? previous;
}

/**
 * „Wróć do kolejki”, gdy osoba w panelu wypadła z kolejki (ruch, filtr):
 * pierwsza osoba, która stała za nią i nadal jest w kolejce, a gdy nikogo
 * takiego nie ma — pierwsza osoba kolejki.
 */
export function returnToQueueTarget(
  queueOrder: readonly number[],
  formerlyAfter: readonly number[],
): number | null {
  const live = new Set(queueOrder);
  return formerlyAfter.find((id) => live.has(id)) ?? queueOrder[0] ?? null;
}

/** Pierwsza kolumna na prawo od `fromIndex`, w której ktoś jest — cel „Dalej: …” (D4). */
export function nextColumnWithPeople<C extends { items: ReadonlyArray<unknown> }>(
  columns: readonly C[],
  fromIndex: number,
): C | null {
  for (let i = fromIndex + 1; i < columns.length; i += 1) {
    if (columns[i].items.length > 0) return columns[i];
  }
  return null;
}
