/**
 * Pamięć Jarvisa w przeglądarce (klucz per osoba). `localStorage` bywa
 * zablokowany (tryb prywatny, polityka firmy) — wtedy funkcje działają bez
 * pamięci, nigdy nie rzucają.
 */

import { warsawToday } from "@/lib/warsaw-date";

export function storageKey(userId: number | undefined, name: string): string {
  return `nexus:jarvis:${name}:v1:${userId ?? "anon"}`;
}

export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage zablokowany — funkcja działa bez pamięci */
  }
}

export function todayKey(): string {
  return warsawToday();
}
