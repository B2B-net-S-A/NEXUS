// Postęp poligonu w P1 trzyma przeglądarka (localStorage). W P2 przechodzi do
// `novelty_progress` (id `poligon-*`), razem z podmianą Startu dla nowych osób.

import { LEVEL_1 } from "./exercises";

const KEY = "nexus.poligon.done";

export function readDone(): Set<string> {
  try {
    const raw = window.localStorage.getItem(KEY);
    const list: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? list.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

export function markDone(id: string): Set<string> {
  const done = readDone();
  done.add(id);
  try {
    window.localStorage.setItem(KEY, JSON.stringify([...done]));
  } catch {
    // bez localStorage postęp zostaje do odświeżenia
  }
  return done;
}

export function resetProgress(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    // nic
  }
}

/** Pierwsze niezaliczone ćwiczenie poziomu 1 (albo `null`, gdy komplet). */
export function nextExerciseId(done: ReadonlySet<string>): string | null {
  return LEVEL_1.find((e) => !done.has(e.id))?.id ?? null;
}
