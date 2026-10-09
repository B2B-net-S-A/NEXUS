/**
 * Karta rekomendacji — prezentacja (0413). Kompletność i wartości liczy
 * serwer; tu tylko kolejność pól, krótkie etykiety i plakietka na tablicy.
 */

import type { RecommendationCard, RecommendationCardField } from "@/lib/api/recommendationCards";

/** Kolejność pól jak we wzorze działu. */
export const CARD_FIELD_ORDER = [
  "rate",
  "availability",
  "work_mode",
  "location",
  "nationality",
  "worked_at_client",
  "english",
  "red_flags",
  "recommendation",
  "motivation",
] as const;

/** Pola wielowierszowe — pole tekstowe zamiast jednej linii. */
export const CARD_MULTILINE_FIELDS: ReadonlySet<string> = new Set([
  "red_flags",
  "recommendation",
  "motivation",
]);

export const CARD_FIELD_HINT: Partial<Record<string, string>> = {
  rate: "np. 135 zł/h netto B2B",
  availability: "np. 1 miesiąc albo od 01.11",
  work_mode: "np. hybrydowo, 2 dni w tygodniu, Łódź",
  worked_at_client: "nie / tak, na B2B / tak, na umowie o pracę",
  english: "najlepiej w skali A1–C2",
  red_flags: "brak albo opis — tylko dla zespołu",
  recommendation: "dlaczego ten kandydat",
};

/** Na ekranie „Notatka” ze wzoru działu nazywa się tak, jak rozumie ją rekruter. */
const UI_LABEL: Partial<Record<string, string>> = {
  recommendation: "Dlaczego ten kandydat",
};

export function cardFieldLabel(card: Pick<RecommendationCard, "labels">, key: string): string {
  return UI_LABEL[key] ?? card.labels[key] ?? key;
}

const WORKED_AT_CLIENT: Record<string, string> = {
  no: "nie pracował",
  yes: "pracował",
  uop: "pracował na umowie o pracę",
  b2b: "pracował na B2B",
};

/** Krótka wartość pola do zwartej karty — z odczytu, a bez niego surowy tekst. */
export function cardFieldValue(key: string, field: RecommendationCardField | undefined): string {
  if (!field) return "";
  const raw = String(field.raw ?? "").trim();
  if (key === "english" && typeof field.level === "string") {
    return field.level === "native" ? "ojczysty" : field.level;
  }
  if (key === "worked_at_client" && typeof field.value === "string") {
    return WORKED_AT_CLIENT[field.value] ?? raw;
  }
  if (key === "red_flags" && field.none === true) return "brak";
  return raw;
}

export function cardFieldSource(field: RecommendationCardField | undefined): string | null {
  if (!field) return null;
  if (field.source === "manual") {
    const who = field.by_name ? ` · ${field.by_name}` : "";
    if (field.origin === "note_ai") return `z notatki (AI)${who}`;
    if (field.origin === "note_rule") return `z notatki${who}`;
    if (field.origin === "phrased") return `zdanie z haseł${who}`;
    return field.by_name ? `wpisał(a) ${field.by_name}` : "wpisane w NEXUSIE";
  }
  if (field.source === "note") return "z notatki";
  return null;
}

/** Pola opisowe karty, które przyjmują „Ułóż w zdanie” (lustro `PHRASABLE_FIELDS`). */
export const CARD_PHRASABLE_FIELDS: ReadonlySet<string> = new Set([
  "recommendation",
  "motivation",
  "red_flags",
]);

/** Plakietka pochodzenia odpowiedzi ze screeningu (0421) — `null` = wpisana ręcznie. */
export function answerOriginBadge(origin: string | null | undefined): string | null {
  if (origin === "phrased") return "zdanie z haseł";
  if (origin === "note_import") return "z notatki";
  // Automat przepisał odpowiedź z notatki (karty z Traffita, 07.10.2026).
  if (origin === "note_sync") return "z notatki (Traffit)";
  if (origin === "reassign_suggested") return "z podpowiedzi Luny";
  return null;
}

/**
 * Odpowiedzi warte „Ułóż w zdanie”: niepuste i pisane hasłami — bez kropki na
 * końcu albo krótsze niż 12 słów.
 */
export function looksLikeKeywords(text: string | null | undefined): boolean {
  const value = String(text ?? "").trim();
  if (!value) return false;
  const words = value.split(/\s+/).length;
  return !/[.!?]$/.test(value) || words < 12;
}

/** Pola, które zmieniły się w formularzu względem karty (`null` = wyczyszczone). */
export function cardChanges(
  card: Pick<RecommendationCard, "fields" | "editable_fields">,
  draft: Record<string, string>,
): Record<string, string | null> {
  const changes: Record<string, string | null> = {};
  for (const key of card.editable_fields) {
    if (!(key in draft)) continue;
    const next = draft[key].trim();
    const current = String(card.fields[key]?.raw ?? "").trim();
    if (next === current) continue;
    changes[key] = next || null;
  }
  return changes;
}

/** „1 próba kontaktu”, „3 próby kontaktu”, „5 prób kontaktu”. */
export function contactAttemptsLabel(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  const word =
    count === 1
      ? "próba"
      : last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)
        ? "próby"
        : "prób";
  return `${count} ${word} kontaktu`;
}

export interface BoardCardState {
  status: "complete" | "partial" | "empty";
  missing: number;
  answers: number;
  rate_hourly?: number | null;
}

export interface BoardCardBadge {
  label: string;
  tone: "ok" | "wait" | "neutral";
  title: string;
}

/**
 * Plakietka screeningu na tablicy: stan pól warunków i oceny (liczy serwer,
 * stawka z etapu też się liczy). W „Screeningu” puste pola też są informacją
 * (albo liczba prób kontaktu). Od 09.10.2026 bez nazwy „karta rekomendacji”.
 */
export function boardCardBadge(
  card: BoardCardState | null | undefined,
  contactAttempts: number,
  column: string | null,
): BoardCardBadge | null {
  if (column !== "screening" && column !== "verified" && column !== "cv_qc") return null;
  if (card && card.status === "complete") {
    return {
      label: "Screening: komplet",
      tone: "ok",
      title: "Wszystkie pola warunków i oceny są wypełnione.",
    };
  }
  if (card && card.status === "partial") {
    return {
      label: `Screening: brakuje ${card.missing}`,
      tone: "wait",
      title: "W screeningu brakuje pól warunków albo oceny — nie blokuje to ruchu karty.",
    };
  }
  if (column !== "screening") {
    return {
      label: "Screening: puste pola",
      tone: "neutral",
      title: "Nikt nie wpisał jeszcze warunków ani oceny tej osoby.",
    };
  }
  if (contactAttempts > 0) {
    return {
      label: contactAttemptsLabel(contactAttempts),
      tone: "neutral",
      title: "Notatki „nie odebrał” — rozmowy jeszcze nie było.",
    };
  }
  return {
    label: "Screening: puste pola",
    tone: "neutral",
    title: "Nikt nie wpisał jeszcze warunków ani oceny tej osoby.",
  };
}
