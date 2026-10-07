/**
 * Telemetria otwarcia „Do przejrzenia” (audyt 06.10.2026).
 *
 * Skrzynka propozycji nie miała pomiaru otwarcia, więc „0 pominięć” nie
 * odróżniało „nikt nie patrzy” od „wszystko dobre”. Serwer zapisuje jedno
 * zdarzenie na (rekrutację, osobę, dzień); przeglądarka wysyła najwyżej jedno
 * żądanie na rekrutację na dzień (klucz w `localStorage` z datą).
 *
 * To pomiar, nie funkcja: bez czekania na wynik, każdy błąd połknięty.
 * Harnessy `/preview/*` nic nie wysyłają (tam i tak blokada zapisów odrzuca
 * POST bez odpowiedzi — nie robimy nawet próby).
 */

import { jobProposalsApi } from "@/lib/job-proposals-api";
import { warsawToday } from "@/lib/warsaw-date";

const STORAGE_PREFIX = "nexus:proposal-inbox-opened:";

export function proposalInboxOpenedKey(jobId: number): string {
  return `${STORAGE_PREFIX}${jobId}`;
}

/** Czy wysłać dziś zdarzenie dla tej rekrutacji — i zapamiętaj, że wysłane. */
function claimToday(jobId: number, today: string): boolean {
  try {
    const key = proposalInboxOpenedKey(jobId);
    if (window.localStorage.getItem(key) === today) return false;
    window.localStorage.setItem(key, today);
  } catch {
    // Bez pamięci przeglądarki wysyłamy — serwer i tak liczy raz na dzień.
  }
  return true;
}

export function recordProposalInboxOpened(jobId: number, now: Date = new Date()): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname.startsWith("/preview")) return;
  if (!claimToday(jobId, warsawToday(now))) return;
  try {
    void jobProposalsApi.opened(jobId).catch(() => undefined);
  } catch {
    // Pomiar nie może psuć ekranu.
  }
}
