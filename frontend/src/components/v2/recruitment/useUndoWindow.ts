"use client";

/**
 * „Cofnij” po „+ Dodaj” w oknie „Kandydaci do dodania” (14.10.2026) działa
 * tylko zaraz po dodaniu — tyle samo co serwer (`UNDO_ADD_WINDOW` w
 * `services/job_proposals.py`, `quick_undo` w trasie usunięcia). Po tym czasie
 * przycisk znika: późniejsze usunięcie z rekrutacji to korekta z panelu osoby,
 * z potwierdzeniem, nie jedno kliknięcie w liście.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export const UNDO_ADD_WINDOW_MS = 15 * 60 * 1000;

/** Klucz osoby (`number`) albo pary osoba × rekrutacja (`string`, „Pasuje też do”). */
export interface UndoWindow<K extends number | string = number> {
  /** Dodano osobę — od teraz liczy się okno „Cofnij”. */
  start: (ids: readonly K[]) => void;
  /** Osoby, którym okno już minęło. */
  expired: ReadonlySet<K>;
}

export function useUndoWindow<K extends number | string = number>(
  windowMs: number = UNDO_ADD_WINDOW_MS,
): UndoWindow<K> {
  const [expired, setExpired] = useState<ReadonlySet<K>>(() => new Set());
  const timers = useRef(new Map<K, ReturnType<typeof setTimeout>>());

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) clearTimeout(timer);
      pending.clear();
    };
  }, []);

  const start = useCallback(
    (ids: readonly K[]) => {
      for (const id of ids) {
        const previous = timers.current.get(id);
        if (previous) clearTimeout(previous);
        setExpired((prev) => {
          if (!prev.has(id)) return prev;
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        timers.current.set(
          id,
          setTimeout(() => {
            timers.current.delete(id);
            setExpired((prev) => new Set([...prev, id]));
          }, windowMs),
        );
      }
    },
    [windowMs],
  );

  return { start, expired };
}
