// „Ostatnia rozmowa” na liście kandydatów i w szybkim podglądzie.
//
// Rozmowa = najnowsza notatka z zakładki „Rozmowy” (serwer:
// `note_kinds.talks_clause`). „Nie odebrał” rozmową nie jest — bez rozmowy
// komórka mówi, ile było prób kontaktu.

import { contactAttemptsLabel } from "@/lib/recommendation-card";

export interface LastTalkSource {
  last_talk_at?: string | null;
  last_talk_by?: string | null;
  last_talk_preview?: string | null;
  contact_attempts?: number | null;
}

export interface LastTalkCell {
  primary: string;
  secondary: string | null;
  /** Wyszarzone — brak rozmowy nie może wyglądać jak wartość. */
  muted: boolean;
  title: string | null;
}

const DAY = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Warsaw",
});

export function lastTalkDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : DAY.format(parsed);
}

export function lastTalkCell(source: LastTalkSource): LastTalkCell {
  const date = lastTalkDate(source.last_talk_at);
  const attempts = Math.max(0, Math.trunc(source.contact_attempts ?? 0));
  if (date) {
    return {
      primary: date,
      secondary: source.last_talk_by?.trim() || "import z Traffita",
      muted: false,
      title: source.last_talk_preview?.trim() || null,
    };
  }
  return {
    primary: "bez rozmowy",
    secondary: attempts > 0 ? contactAttemptsLabel(attempts) : null,
    muted: true,
    title:
      attempts > 0
        ? "Były tylko próby kontaktu („nie odebrał”) — rozmowy jeszcze nie zapisano."
        : null,
  };
}
