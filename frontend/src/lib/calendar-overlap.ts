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
  /** Numer grupy nachodzących wydarzeń w tej kolumnie dnia. */
  cluster: number;
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
  let clusterIndex = 0;

  const flush = () => {
    for (const item of cluster) {
      result.set(item.id, {
        column: item.column,
        columns: columnEnds.length,
        cluster: clusterIndex,
      });
    }
    if (cluster.length > 0) clusterIndex += 1;
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

/** Ile pasów mieści się czytelnie w kolumnie dnia widoku tygodniowego. */
export const MAX_VISIBLE_LANES = 2;

export interface VisibleOverlapSlot extends OverlapSlot {
  /** Wydarzenie nie mieści się w widocznych pasach — trafia do „+N”. */
  hidden: boolean;
}

export interface OverflowGroup {
  cluster: number;
  /** Góra grupy (najwcześniejszy start) — tam stoi chip „+N”. */
  top: number;
  ids: Array<string | number>;
}

/**
 * Przy 3+ równoległych wydarzeniach pasy robiły się wąskie jak ikona, a tytuły
 * skracały się do „Sp…” (UAT B08). Pokazujemy najwyżej `maxLanes` pasów;
 * pozostałe wydarzenia grupy trafiają do chipa „+N” otwierającego ich listę.
 */
export function limitVisibleLanes(
  events: readonly OverlapInput[],
  slots: Map<string | number, OverlapSlot>,
  maxLanes: number = MAX_VISIBLE_LANES,
): { slots: Map<string | number, VisibleOverlapSlot>; overflow: OverflowGroup[] } {
  const visible = new Map<string | number, VisibleOverlapSlot>();
  const groups = new Map<number, OverflowGroup>();
  for (const ev of events) {
    const slot = slots.get(ev.id);
    if (!slot) continue;
    const overflowing = slot.columns > maxLanes;
    const hidden = overflowing && slot.column >= maxLanes;
    visible.set(ev.id, { ...slot, columns: overflowing ? maxLanes : slot.columns, hidden });
    if (overflowing) {
      const group = groups.get(slot.cluster) ?? { cluster: slot.cluster, top: ev.start, ids: [] };
      group.top = Math.min(group.top, ev.start);
      if (hidden) group.ids.push(ev.id);
      groups.set(slot.cluster, group);
    }
  }
  return { slots: visible, overflow: [...groups.values()].filter((g) => g.ids.length > 0) };
}
