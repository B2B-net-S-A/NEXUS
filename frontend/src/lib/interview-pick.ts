/**
 * Okno „Umów rozmowę i prepy” (20.10.2026, PR 2) — logika bez Reacta.
 *
 * Rekruter po telefonie do kandydata wybiera termin od klienta (w oknie
 * klienta także godzinę) i od razu godziny obu prepów z podpowiedzi serwera.
 * Godziny pól liczymy w czasie przeglądarki, jak reszta okien terminów.
 */
import type { SlotItem } from "@/lib/interview-cycle";

const pad = (n: number) => String(n).padStart(2, "0");

export function hhmm(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function isWindow(slot: SlotItem): boolean {
  return Boolean(slot.window_end && slot.end && new Date(slot.window_end) > new Date(slot.end));
}

/** Najwcześniejsza i najpóźniejsza godzina startu rozmowy w oknie klienta. */
export function windowBounds(slot: SlotItem, durationMinutes: number): { from: string; to: string } | null {
  if (!isWindow(slot)) return null;
  const latest = new Date(new Date(slot.window_end as string).getTime() - durationMinutes * 60_000);
  return { from: hhmm(slot.start), to: hhmm(latest.toISOString()) };
}

/**
 * Start rozmowy dla wybranego terminu: zwykły termin — jego start; okno —
 * dzień okna i godzina z pola. `null`, gdy godzina jest pusta albo poza oknem.
 */
export function interviewStart(slot: SlotItem, time: string, durationMinutes: number): string | null {
  const bounds = windowBounds(slot, durationMinutes);
  if (!bounds) return new Date(slot.start).toISOString();
  if (!/^\d{2}:\d{2}$/.test(time) || time < bounds.from || time > bounds.to) return null;
  const day = new Date(slot.start);
  const [h, m] = time.split(":").map(Number);
  day.setHours(h, m, 0, 0);
  return day.toISOString();
}

const WHEN = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** „śr., 21.10, 16:00” — etykieta godziny prepu. */
export function prepWhen(iso: string): string {
  return WHEN.format(new Date(iso));
}

/** Okno kandydata „od–do” jest poprawne albo puste (wtedy godziny pracy). */
export function candidateWindowError(from: string, to: string): string | null {
  if (from && to && to <= from) return "Koniec musi być po początku.";
  return null;
}
