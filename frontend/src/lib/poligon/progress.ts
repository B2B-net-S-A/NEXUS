// Postęp poligonu. Serwer (`novelty_progress`, id `poligon-…`) jest źródłem
// prawdy: na nim stoi blokada pracy nowej osoby i dzień onboardingu poza
// statystykami. `localStorage` to tylko pamięć podręczna — mapa i panel
// ćwiczenia pokazują zaliczenie od razu, zanim wróci odpowiedź serwera.

import { api } from "@/lib/api";

import { EXERCISES } from "./exercises";

const KEY = "nexus.poligon.done";
/** „Przejdź jeszcze raz”: mapa liczy od zera, choć serwer pamięta zaliczenie. */
const REPLAY_KEY = "nexus.poligon.replay";
export const SERVER_PREFIX = "poligon-";

function readLocal(): Set<string> {
  try {
    const raw = window.localStorage.getItem(KEY);
    const list: unknown = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(list) ? list.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function writeLocal(done: ReadonlySet<string>): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify([...done]));
  } catch {
    // bez localStorage zostaje stan z serwera
  }
}

/** Zaliczone ćwiczenia: pamięć przeglądarki plus to, co zna serwer. */
export function readDone(serverIds: readonly string[] = []): Set<string> {
  const done = readLocal();
  if (replaying()) return done;
  for (const id of serverIds) done.add(id.startsWith(SERVER_PREFIX) ? id.slice(SERVER_PREFIX.length) : id);
  return done;
}

const pending = new Set<Promise<unknown>>();

/** Zalicza ćwiczenie: od razu w przeglądarce, w tle na serwerze. */
export function markDone(id: string): Set<string> {
  const done = readLocal();
  done.add(id);
  writeLocal(done);
  const request = api
    .post(`/api/novelties/${SERVER_PREFIX}${id}/events`, { event: "used" })
    .catch((error: unknown) => {
      // Osoba spoza ról poligonu (404) ćwiczy bez zapisu na serwerze.
      console.warn("[poligon] zaliczenie nie trafiło na serwer:", id, error);
    })
    .finally(() => pending.delete(request));
  pending.add(request);
  return done;
}

/** Czeka na zapisy zaliczeń — przed wyjściem z poligonu, żeby blokada już ich nie liczyła. */
export async function flushProgress(): Promise<void> {
  await Promise.allSettled([...pending]);
}

function replaying(): boolean {
  try {
    return window.localStorage.getItem(REPLAY_KEY) === "1";
  } catch {
    return false;
  }
}

/** „Przejdź jeszcze raz” — od zera w tej przeglądarce; serwer pamięta zaliczenie. */
export function resetProgress(): void {
  try {
    window.localStorage.removeItem(KEY);
    window.localStorage.setItem(REPLAY_KEY, "1");
  } catch {
    // nic
  }
}

/** Pierwsze niezaliczone ćwiczenie (albo `null`, gdy komplet). */
export function nextExerciseId(done: ReadonlySet<string>): string | null {
  return EXERCISES.find((e) => !done.has(e.id))?.id ?? null;
}
