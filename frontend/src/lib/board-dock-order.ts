/**
 * Kolejność nawigatora doku „‹ N z M ›" na Tablicy — DOKŁADNIE ta, którą widać:
 * kolumny od lewej (złożone kolumny Tablicy, rozwinięci zamknięci, „Poza
 * szablonem"), karty od góry w kolejności renderu.
 *
 * Do 24.09.2026 dok liczył kolejność z surowych etapów szablonu, więc pierwsza
 * karta w „Nowi" miała „12 z 35", a „←" prowadziło do ostatniej karty kolumny.
 * Do 02.10.2026 pomijał karty przygaszone filtrami — pasek filtrów zniknął.
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
