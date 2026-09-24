/**
 * Kolejność nawigatora doku „‹ N z M ›" na Tablicy — DOKŁADNIE ta, którą widać:
 * kolumny od lewej (złożone kolumny Tablicy, rozwinięci zamknięci, „Poza
 * szablonem"), karty od góry w kolejności renderu. Karty przygaszone filtrem
 * („Mój ruch", nazwisko, utknęli…) nawigator pomija — poza kartą otwartą
 * w doku, żeby „N z M" nie znikało po włączeniu filtra.
 *
 * Do 24.09.2026 dok liczył kolejność z surowych etapów szablonu, więc pierwsza
 * karta w „Nowi" miała „12 z 35", a „←" prowadziło do ostatniej karty kolumny.
 */

export function dockNavigationOrder<T extends { candidate_id: number }>(
  columns: ReadonlyArray<{ items: ReadonlyArray<T> }>,
  isDimmed: (item: T) => boolean,
  currentCandidateId: number | null,
): number[] {
  const order: number[] = [];
  const seen = new Set<number>();
  for (const col of columns) {
    for (const item of col.items) {
      if (seen.has(item.candidate_id)) continue;
      if (item.candidate_id !== currentCandidateId && isDimmed(item)) continue;
      seen.add(item.candidate_id);
      order.push(item.candidate_id);
    }
  }
  return order;
}
