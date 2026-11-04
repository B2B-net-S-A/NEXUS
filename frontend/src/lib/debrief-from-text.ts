/**
 * „Po rozmowie” (20.10.2026, PR 4): pytania klienta, oferta i stawka
 * rozpisane z notatki z telefonu do kandydata. Serwer zwraca tylko elementy
 * z cytatem z notatki; tu typy i jedno zdanie podsumowania.
 */
import type { OfferAcceptance } from "@/lib/interview-cycle";

export interface DebriefFromText {
  status: "ok" | "empty" | "unavailable";
  message: string | null;
  questions: { text: string; quote: string }[];
  offer: { value: OfferAcceptance; condition: string | null; quote: string } | null;
  rate: { amount: string; unit: "hourly" | "daily" | "monthly" | null; quote: string } | null;
  start: { text: string; quote: string } | null;
  dropped: number;
}

function countPl(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (n === 1) return `${n} ${one}`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${n} ${few}`;
  return `${n} ${many}`;
}

/** „Uzupełnione z notatki: 3 pytania, oferta, stawka. Sprawdź przed zapisem.” */
export function debriefFillSummary(result: DebriefFromText): string {
  if (result.status !== "ok") return result.message ?? "Nie udało się rozpisać notatki.";
  const parts = [
    result.questions.length ? countPl(result.questions.length, "pytanie", "pytania", "pytań") : null,
    result.offer ? "oferta" : null,
    result.rate ? "stawka" : null,
    result.start ? "start" : null,
  ].filter(Boolean);
  return `Uzupełnione z notatki: ${parts.join(", ")}. Sprawdź przed zapisem.`;
}

/** Komentarz debriefu: notatka (i start, jeśli notatka go nie zawiera dosłownie). */
export function commentFromNote(note: string, result: DebriefFromText, limit = 4000): string {
  const text = note.trim();
  const withStart = result.start && !text.includes(result.start.text) ? `${text}\nStart: ${result.start.text}` : text;
  return withStart.slice(0, limit);
}
