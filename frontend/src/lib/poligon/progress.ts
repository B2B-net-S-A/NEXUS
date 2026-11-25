// Postęp poligonu. Serwer (`novelty_progress`, id `poligon-…`) jest źródłem
// prawdy: na nim stoi blokada pracy nowej osoby i dzień onboardingu poza
// statystykami. `localStorage` to tylko pamięć podręczna — mapa i panel
// ćwiczenia pokazują zaliczenie od razu, zanim wróci odpowiedź serwera.

import { api } from "@/lib/api";

import type { Exercise } from "./exercises";

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

/**
 * Zalicza ćwiczenie: od razu w przeglądarce, w tle na serwerze. `broken` to
 * „Coś nie działa — zalicz i dalej” (Artur, 25.11.2026): serwer zalicza tak samo
 * i zapisuje ślad, które ćwiczenie jest zepsute.
 */
export function markDone(id: string, opts: { broken?: boolean } = {}): Set<string> {
  const done = readLocal();
  done.add(id);
  writeLocal(done);
  const url = `/api/novelties/${SERVER_PREFIX}${id}/events`;
  const request = api
    .post(url, { event: opts.broken ? "broken" : "used" })
    // Serwer bez zdarzenia `broken` (front wdrożony przed backendem) odpowiada
    // 422 — zaliczenie i tak ma dojść, więc ponawiamy zwykłym „used”.
    .catch((error: unknown) => (opts.broken ? api.post(url, { event: "used" }) : Promise.reject(error)))
    .catch((error: unknown) => {
      // Osoba spoza ról poligonu (404) ćwiczy bez zapisu na serwerze.
      console.warn("[poligon] zaliczenie nie trafiło na serwer:", id, error);
    })
    .finally(() => pending.delete(request));
  pending.add(request);
  return done;
}

const resent = new Set<string>();

/**
 * Dosyła serwerowi ćwiczenia zaliczone w tej przeglądarce, których serwer nie
 * zna. Zapis idzie w tle i nieudany kończy się tylko ostrzeżeniem, a blokada
 * liczy z serwera: 25.11.2026 osoba widziała „27 z 27 · Poligon zaliczony”,
 * serwer miał 26 i NEXUS jej nie przepuszczał. Każde id raz na wczytanie strony.
 */
export function resendMissing(serverIds: readonly string[], path: readonly Exercise[]): string[] {
  if (replaying()) return [];
  const onServer = new Set(serverIds.map((id) => (id.startsWith(SERVER_PREFIX) ? id.slice(SERVER_PREFIX.length) : id)));
  const missing = path
    .map((e) => e.id)
    .filter((id) => readLocal().has(id) && !onServer.has(id) && !resent.has(id));
  for (const id of missing) {
    resent.add(id);
    markDone(id);
  }
  return missing;
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

/** Pierwsze niezaliczone ćwiczenie ścieżki osoby (albo `null`, gdy komplet). */
export function nextExerciseId(done: ReadonlySet<string>, path: readonly Exercise[]): string | null {
  return path.find((e) => !done.has(e.id))?.id ?? null;
}
