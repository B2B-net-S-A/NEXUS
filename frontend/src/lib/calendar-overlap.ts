/**
 * Układ nachodzących wydarzeń w kolumnie dnia kalendarza tygodniowego.
 *
 * Każde wydarzenie było pozycjonowane `absolute left-1 right-1`, więc dwa
 * spotkania o tej samej godzinie leżały dokładnie na sobie — widoczne było
 * tylko ostatnie, a reszta tworzyła nieczytelny stos (UAT M03-B11). Tu
 * wydarzenia nachodzące na siebie (także pośrednio, łańcuchem) dzielą szerokość
 * kolumny dnia na równe pasy, jak w każdym kalendarzu.
 *
 * Czysta funkcja na przedziałach liczbowych (np. pikselach `top`/`top+height`),
 * żeby dało się ją testować bez renderu i żeby minimalna wysokość kafla
 * (a nie tylko czas trwania) decydowała, czy kafle na siebie nachodzą.
 */
export interface OverlapInput {
  id: string | number;
  start: number;
  end: number;
}

export interface OverlapSlot {
  /** Indeks pasa (0 = lewy). */
  column: number;
  /** Liczba pasów w grupie nachodzących wydarzeń. */
  columns: number;
}

export function layoutOverlappingEvents(
  events: readonly OverlapInput[],
): Map<string | number, OverlapSlot> {
  const sorted = [...events].sort(
    (a, b) => a.start - b.start || b.end - a.end,
  );
  const result = new Map<string | number, OverlapSlot>();

  let cluster: { id: string | number; column: number }[] = [];
  let columnEnds: number[] = [];
  let clusterEnd = -Infinity;

  const flush = () => {
    for (const item of cluster) {
      result.set(item.id, { column: item.column, columns: columnEnds.length });
    }
    cluster = [];
    columnEnds = [];
    clusterEnd = -Infinity;
  };

  for (const ev of sorted) {
    const end = Math.max(ev.end, ev.start);
    if (cluster.length > 0 && ev.start >= clusterEnd) flush();
    let column = columnEnds.findIndex((colEnd) => colEnd <= ev.start);
    if (column === -1) {
      column = columnEnds.length;
      columnEnds.push(end);
    } else {
      columnEnds[column] = end;
    }
    cluster.push({ id: ev.id, column });
    clusterEnd = Math.max(clusterEnd, end);
  }
  flush();
  return result;
}
