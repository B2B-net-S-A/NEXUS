"use client";

// Przegląd „po kolei” — kolejka osób do przejrzenia jedna po drugiej.
//
// Wzorzec z kolejki Cpro (`CproQueueDialog`): migawka kolejności w chwili
// startu i zbiór osób już załatwionych w tej sesji. Lista z serwera odświeża
// się po każdej decyzji, więc „następna osoba” liczona z samej listy skakałaby
// — migawka trzyma kolejność i licznik „2 z 5”, a dane bieżącej osoby zawsze
// pochodzą z żywej listy. Osoba, która zniknęła z listy (ktoś inny ją wysłał),
// jest pomijana.

import { useCallback, useMemo, useState } from "react";

export interface ReviewSequence<T> {
  /** Kolejka została uruchomiona i nikt jej nie zakończył. */
  active: boolean;
  /** Osoba do pokazania; `null` przy `active` = wszyscy załatwieni — wołający
   *  kończy kolejkę (`finish`). */
  current: T | null;
  /** Pozycja bieżącej osoby w migawce, od 1. */
  position: number;
  total: number;
  /** Start od pierwszej osoby listy (albo od `startId`, gdy jest na liście). */
  start: (items: readonly T[], startId?: number) => void;
  /** Bieżąca osoba załatwiona decyzją — następna. */
  advance: () => void;
  /** „Pomiń”: następna osoba, a pominięta DALEJ czeka w kolejce na serwerze —
   *  komunikat na koniec nie może mówić, że nikt już nie czeka. */
  skip: () => void;
  /** Ile osób pominięto w tej kolejce. */
  skipped: number;
  finish: () => void;
}

interface State {
  order: number[];
  done: ReadonlySet<number>;
  skipped: number;
}

export function useReviewSequence<T>(
  live: readonly T[],
  idOf: (item: T) => number,
): ReviewSequence<T> {
  const [state, setState] = useState<State | null>(null);

  const current = useMemo(() => {
    if (!state) return null;
    const byId = new Map(live.map((item) => [idOf(item), item]));
    for (const id of state.order) {
      if (state.done.has(id)) continue;
      const item = byId.get(id);
      if (item !== undefined) return item;
    }
    return null;
  }, [state, live, idOf]);

  const start = useCallback(
    (items: readonly T[], startId?: number) => {
      const ids = items.map(idOf);
      const from = startId === undefined ? 0 : Math.max(ids.indexOf(startId), 0);
      // Start od wskazanej osoby; wcześniejsze idą na koniec, nie przepadają.
      setState({ order: [...ids.slice(from), ...ids.slice(0, from)], done: new Set(), skipped: 0 });
    },
    [idOf],
  );

  const currentId = current === null ? null : idOf(current);
  const leave = useCallback(
    (skippedNow: number) => {
      if (currentId === null) return;
      setState((prev) =>
        prev
          ? { ...prev, done: new Set(prev.done).add(currentId), skipped: prev.skipped + skippedNow }
          : prev,
      );
    },
    [currentId],
  );
  const advance = useCallback(() => leave(0), [leave]);
  const skip = useCallback(() => leave(1), [leave]);

  const finish = useCallback(() => setState(null), []);

  return {
    active: state !== null,
    current,
    position: state && currentId !== null ? state.order.indexOf(currentId) + 1 : 0,
    total: state?.order.length ?? 0,
    start,
    advance,
    skip,
    skipped: state?.skipped ?? 0,
    finish,
  };
}
