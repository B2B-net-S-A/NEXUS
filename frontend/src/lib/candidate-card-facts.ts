// Ustalenia z kart rekomendacji w profilu kandydata — czyste reguły opisu.
//
// Pasek faktów pokazuje wartość z PROFILU (po niej filtruje lista); karta
// dokłada pod nią, co i kiedy ustalono w rozmowie. Gdy obie wartości są tą
// samą liczbą, wystarcza samo źródło z datą.

import type {
  CandidateCardConversation,
  CandidateCardFact,
  CandidateCardNoteLink,
} from "@/lib/api/candidateCards";
import { countPl } from "@/lib/plural-pl";

const DAY = new Intl.DateTimeFormat("pl-PL", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  timeZone: "Europe/Warsaw",
});

function day(value: string | null): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : DAY.format(parsed);
}

export function cardFactsByKey(
  facts: readonly CandidateCardFact[] | undefined,
): Partial<Record<string, CandidateCardFact>> {
  return Object.fromEntries((facts ?? []).map((fact) => [fact.key, fact]));
}

/** „rozmowa 28.09.2026” albo „wpisane na karcie 28.09.2026”. */
export function cardFactOrigin(fact: CandidateCardFact): string {
  const date = day(fact.at);
  const what = fact.source === "manual" ? "wpisane na karcie" : "rozmowa";
  return date ? `${what} ${date}` : what;
}

/** Dymek: kto i w której rekrutacji. */
export function cardFactTitle(fact: CandidateCardFact): string {
  const parts = [
    fact.source === "manual" ? "Wpisane na karcie rekomendacji" : "Z notatki-karty rekomendacji",
    fact.author_name,
    fact.job_title,
  ].filter(Boolean);
  return parts.join(" · ");
}

function shorten(text: string, limit = 80): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit - 1).trimEnd()}…` : clean;
}

/**
 * Linia pod wartością z profilu. `profileAmount` podajemy tylko dla stawki:
 * ta sama liczba = samo źródło, inna = źródło z wartością z rozmowy.
 */
export function cardFactLine(
  fact: CandidateCardFact | undefined,
  profileAmount?: number | null,
): string | null {
  if (!fact || !fact.raw.trim()) return null;
  const origin = cardFactOrigin(fact);
  if (
    fact.key === "rate" &&
    typeof fact.value === "number" &&
    profileAmount != null &&
    Math.abs(fact.value - profileAmount) < 0.005
  ) {
    return origin;
  }
  return `${origin}: ${shorten(fact.raw)}`;
}

/** Rozmowy z kart dla rekrutacji, które nie mają arkusza screeningu. */
export function conversationsWithoutSheet(
  conversations: readonly CandidateCardConversation[] | undefined,
  sheetJobIds: ReadonlySet<number>,
): CandidateCardConversation[] {
  return (conversations ?? []).filter((item) => !sheetJobIds.has(item.job_id));
}

/** „28.09.2026 · 2 z 3 pytań · z karty wpisanej w Traffit”. */
export function cardConversationMeta(conversation: CandidateCardConversation): string {
  const answered = conversation.answers.length;
  const total = Math.max(conversation.question_count, answered);
  const parts = [
    day(conversation.answered_at),
    answered === total
      ? countPl(total, "pytanie", "pytania", "pytań")
      : `${answered} z ${countPl(total, "pytania", "pytań", "pytań")}`,
    conversation.from_traffit ? "z karty wpisanej w Traffit" : "z notatki",
  ];
  return parts.filter(Boolean).join(" · ");
}

export function noteLinksById(
  links: readonly CandidateCardNoteLink[] | undefined,
): Map<number, CandidateCardNoteLink> {
  return new Map((links ?? []).map((link) => [link.note_id, link]));
}

/** „Do karty trafiło: stawka, dostępność, tryb pracy i 2 odpowiedzi”. */
export function noteLinkSummary(link: CandidateCardNoteLink): string | null {
  const parts = link.field_labels.map((label) => label.toLowerCase());
  if (link.answers > 0) {
    parts.push(countPl(link.answers, "odpowiedź", "odpowiedzi", "odpowiedzi"));
  }
  if (parts.length === 0) return null;
  const last = parts.length > 1 ? ` i ${parts.pop()}` : "";
  return `Do karty trafiło: ${parts.join(", ")}${last}`;
}
