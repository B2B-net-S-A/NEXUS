/**
 * Podpowiedzi stawki i dostępności z notatek (`suggestions` w odpowiedzi
 * `GET /api/pipeline/stages/{id}/screening`, backend: `screening_suggestions.py`).
 *
 * Serwer niczego nie zapisuje i my też nie: „Użyj" wypełnia pole formularza
 * tak, jakby rekruter je wpisał, a do bazy trafia dopiero zwykłym zapisem.
 */

import type { RateUnit } from "@/lib/api";

export interface ScreeningRateSuggestion {
  value: number;
  unit: "hour" | "day" | "month" | null;
  currency: string | null;
  raw: string | null;
  source_note_id: number | null;
  noted_at: string | null;
}

export interface ScreeningAvailabilitySuggestion {
  raw: string | null;
  notice_period: string | null;
  available_from: string | null;
  source_note_id: number | null;
  noted_at: string | null;
}

export interface ScreeningSuggestions {
  rate?: ScreeningRateSuggestion;
  availability?: ScreeningAvailabilitySuggestion;
  /** Stawka istnieje, ale ta rola jej nie widzi — nie rysujemy podpowiedzi. */
  rate_redacted?: boolean;
}

const UNIT_TO_FORM: Record<string, RateUnit> = {
  hour: "hourly",
  day: "daily",
  month: "monthly",
};

const UNIT_SUFFIX: Record<string, string> = { hour: "h", day: "dzień", month: "mies." };

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/;

/** „12.09" z daty ISO; tekst, którego nie umiemy odczytać, pomijamy. */
export function notedAtLabel(value: string | null | undefined): string | null {
  const match = value ? ISO_DATE.exec(value) : null;
  return match ? `${match[3]}.${match[2]}` : null;
}

function isoDatePl(value: string): string {
  const match = ISO_DATE.exec(value);
  return match ? `${match[3]}.${match[2]}.${match[1]}` : value;
}

function amount(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(".", ",");
}

/** „175 zł/h · 12.09" — sama treść, bez przedrostka „Z notatek:". */
export function rateSuggestionLabel(rate: ScreeningRateSuggestion): string {
  const currency = !rate.currency || rate.currency === "PLN" ? "zł" : rate.currency;
  const unit = rate.unit ? `/${UNIT_SUFFIX[rate.unit] ?? rate.unit}` : "";
  const noted = notedAtLabel(rate.noted_at);
  return `${amount(rate.value)} ${currency}${unit}${noted ? ` · ${noted}` : ""}`;
}

/**
 * Wartości do pól stawki albo `null`, gdy podpowiedzi nie da się wpisać bez
 * zgadywania: formularz liczy w PLN, a jednostka musi być znana.
 */
export function rateSuggestionFill(
  rate: ScreeningRateSuggestion,
): { rate: string; unit: RateUnit } | null {
  if (rate.currency && rate.currency !== "PLN") return null;
  const unit = rate.unit ? UNIT_TO_FORM[rate.unit] : undefined;
  if (!unit) return null;
  return { rate: String(rate.value), unit };
}

/** „dostępny od razu" / „od 01.10.2026 · wypowiedzenie: 1 miesiąc". */
export function availabilitySuggestionText(
  availability: ScreeningAvailabilitySuggestion,
): string | null {
  const raw = availability.raw?.trim();
  if (raw) return raw;
  const parts = [
    availability.available_from ? `od ${isoDatePl(availability.available_from.trim())}` : null,
    availability.notice_period ? `wypowiedzenie: ${availability.notice_period.trim()}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

const AVAILABILITY_PREFIX = "Dostępność (z notatek): ";

/**
 * Arkusz nie ma osobnego pola dostępności — trafia ona do „Notatek rekrutera".
 * Dopisujemy linię (nigdy nie nadpisujemy tekstu) i nie dublujemy jej.
 */
export function notesWithAvailability(notes: string, availabilityText: string): string {
  const line = `${AVAILABILITY_PREFIX}${availabilityText}`;
  if (notes.includes(line)) return notes;
  const base = notes.trimEnd();
  return base ? `${base}\n${line}` : line;
}
