/**
 * Uproszczone filtry listy kandydatów (makieta 22.09.2026,
 * https://claude.ai/artifact/FZL7d1BycnJ4vXWB6ncf1s).
 *
 * Dwie rzeczy dla osoby, która nie zna filtrów:
 *
 * 1. JEDNO pytanie „Czy można go teraz zaproponować?" zamiast trzech grup
 *    mówiących o tym samym innymi słowami (Dostępność, Zatrudnienie, Status).
 *    Pytanie ma jedną odpowiedź, więc łączy dwa parametry API tak, żeby wynik
 *    znaczył to, co mówi etykieta: „szuka pracy" samo z siebie zostawiałoby
 *    na liście konsultantów pracujących u naszego klienta.
 * 2. Gotowe skróty nad listą — jeden klik ustawia kilka filtrów.
 *
 * Czyste funkcje, bez Reacta — testowane na wartościach.
 */

import type { CandidateFilters } from "@/lib/url-filters";

type Fields = Pick<
  CandidateFilters,
  "availability" | "employment" | "pipelineStage" | "sentToClientFrom" | "sentToClientTo"
>;

const sameSet = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((v) => b.includes(v));

// ── 1. „Czy można go teraz zaproponować?" ─────────────────────────────────

export type AvailabilityChoiceId = "all" | "open" | "at_client" | "not_looking" | "unknown";

export interface AvailabilityChoice {
  id: AvailabilityChoiceId;
  label: string;
  hint?: string;
  patch: Pick<CandidateFilters, "availability" | "employment">;
}

export const AVAILABILITY_CHOICES: readonly AvailabilityChoice[] = [
  { id: "all", label: "Bez znaczenia", patch: { availability: [], employment: [] } },
  {
    id: "open",
    label: "Tak — szuka pracy albo jest otwarty",
    hint: "nie pracuje teraz u naszego klienta",
    patch: { availability: ["actively_looking", "open_to_offers"], employment: ["available"] },
  },
  {
    id: "at_client",
    label: "Pracuje u naszego klienta",
    hint: "nasz konsultant na projekcie",
    patch: { availability: [], employment: ["at_client"] },
  },
  {
    id: "not_looking",
    label: "Nie szuka",
    patch: { availability: ["not_looking"], employment: ["available"] },
  },
  {
    id: "unknown",
    label: "Nie wiemy",
    hint: "brak informacji o dostępności",
    patch: { availability: ["unknown"], employment: ["available"] },
  },
];

/**
 * Która odpowiedź pasuje do bieżących filtrów. `null` = ustawienie spoza
 * pytania (stary link, zapisane wyszukiwanie) — pokazujemy je uczciwie jako
 * „własne ustawienie", zamiast zaznaczać odpowiedź, która go nie opisuje.
 */
export function availabilityChoiceFor(
  filters: Pick<CandidateFilters, "availability" | "employment">,
): AvailabilityChoiceId | null {
  const hit = AVAILABILITY_CHOICES.find(
    (c) =>
      sameSet(c.patch.availability, filters.availability) &&
      sameSet(c.patch.employment, filters.employment),
  );
  return hit?.id ?? null;
}

// ── 2. Gotowe skróty ──────────────────────────────────────────────────────

export type QuickFilterId = "ready" | "at_client" | "hired_before" | "sent_recently";

export interface QuickFilter {
  id: QuickFilterId;
  label: string;
  /** Jednym zdaniem, co ustawia — tooltip przycisku. */
  description: string;
  apply: (today: Date) => Partial<CandidateFilters>;
  /** Zdjęcie skrótu czyści WYŁĄCZNIE jego pola. */
  clear: Partial<CandidateFilters>;
  isActive: (filters: Fields, today: Date) => boolean;
}

export const SENT_RECENTLY_DAYS = 90;

function isoDaysAgo(today: Date, days: number): string {
  const d = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

const choicePatch = (id: AvailabilityChoiceId) =>
  AVAILABILITY_CHOICES.find((c) => c.id === id)!.patch;

export const QUICK_FILTERS: readonly QuickFilter[] = [
  {
    id: "ready",
    label: "Do zaproponowania teraz",
    description: "Szukają pracy albo są otwarci i nie pracują teraz u naszego klienta.",
    apply: () => ({ ...choicePatch("open") }),
    clear: { ...choicePatch("all") },
    isActive: (f) => availabilityChoiceFor(f) === "open",
  },
  {
    id: "at_client",
    label: "Pracują u naszego klienta",
    description: "Nasi konsultanci, którzy są teraz na projekcie.",
    apply: () => ({ ...choicePatch("at_client") }),
    clear: { ...choicePatch("all") },
    isActive: (f) => availabilityChoiceFor(f) === "at_client",
  },
  {
    id: "hired_before",
    label: "Zatrudnialiśmy ich",
    description: "Kandydaci, którzy doszli w naszej rekrutacji do etapu „Zatrudniony”.",
    apply: () => ({ pipelineStage: ["hired"] }),
    clear: { pipelineStage: [] },
    isActive: (f) => sameSet(f.pipelineStage, ["hired"]),
  },
  {
    id: "sent_recently",
    label: "Wysłani do klienta — 3 mies.",
    description: "Ich CV trafiło do klienta w ostatnich 3 miesiącach.",
    apply: (today) => ({
      sentToClientFrom: isoDaysAgo(today, SENT_RECENTLY_DAYS),
      sentToClientTo: "",
    }),
    clear: { sentToClientFrom: "", sentToClientTo: "" },
    isActive: (f, today) =>
      f.sentToClientTo === "" && f.sentToClientFrom === isoDaysAgo(today, SENT_RECENTLY_DAYS),
  },
];

/** Klik w skrót: włączony — zdejmuje jego pola, wyłączony — ustawia je. */
export function toggleQuickFilter(
  quick: QuickFilter,
  filters: Fields,
  today: Date,
): Partial<CandidateFilters> {
  return quick.isActive(filters, today) ? { ...quick.clear } : quick.apply(today);
}
