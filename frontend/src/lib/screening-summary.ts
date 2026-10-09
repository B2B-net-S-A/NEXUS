/**
 * Widok „Screening” tylko do odczytu (09.10.2026) — czysta logika bez zapytań.
 *
 * Decyzja Artura 09.10.2026: nazwa „Karta rekomendacji” znika z ekranów,
 * a dok osoby, przegląd Delivery Leada, zakończony proces i profil kandydata
 * pokazują JEDEN widok w kolejności formularza: warunki → pytania → ocena.
 * Dane liczy serwer (`GET /api/screening-form`); tu tylko złożenie wierszy
 * i krótkie napisy. Moduł nie importuje formularza — czyta go też profil.
 */

import type { ScreeningFormCard, ScreeningFormState } from "@/lib/api/screeningForm";
import type { BoardCardState } from "@/lib/recommendation-card";
import { SCREENING_FIT_LABEL } from "@/lib/screening-conversations";
import type { ScreeningAnswerRow } from "@/components/v2/screening/ScreeningAnswersList";

/** Adres formularza screeningu osoby (panel osoby na zakładce „Screening”). */
export function screeningFormHref(jobId: number, candidateId: number): string {
  return `/jobs/${jobId}?candidate=${candidateId}&panel=screening`;
}

function sameText(a: string | null | undefined, b: string | null | undefined): boolean {
  return String(a ?? "").trim() === String(b ?? "").trim();
}

/**
 * Wiersze pytań widoku: pytania z Profilu Championa z odpowiedzią z arkusza,
 * a bez niej z notatki; na końcu odpowiedzi arkusza na pytania, których
 * w profilu już nie ma.
 *
 * Identyfikatory pytań są pozycyjne, więc treść pytania bierzemy ze stempla
 * odpowiedzi (`question_text`), a „Odpada, gdy…” doklejamy tylko wtedy, gdy
 * odpowiedź dotyczy tego samego pytania co w profilu.
 */
export function screeningSummaryRows(
  state: Pick<ScreeningFormState, "questions" | "sheet">,
): ScreeningAnswerRow[] {
  const sheetAnswers = state.sheet?.answers ?? [];
  if (!state.questions) {
    // Serwer sprzed 09.10.2026 (okno wdrożenia): same odpowiedzi arkusza.
    return sheetAnswers.map((answer, index) => ({ ...answer, position: index + 1 }));
  }
  const byId = new Map(sheetAnswers.map((answer) => [answer.question_id, answer]));
  const rows: ScreeningAnswerRow[] = state.questions.map((question) => {
    const sheet = question.question_id ? byId.get(question.question_id) : undefined;
    const fromSheet = question.source === "sheet" ? sheet : undefined;
    const stamped = fromSheet?.question_text?.trim() || null;
    return {
      question_id: question.question_id ?? `note:${question.number}`,
      question_text: stamped ?? (question.question.trim() || null),
      response: question.answer,
      deal_breaker_hit: question.deal_breaker_hit,
      skipped: !question.answer.trim() && sheet?.skipped === true,
      origin: fromSheet?.origin ?? question.origin ?? null,
      keywords: fromSheet?.keywords ?? question.keywords ?? null,
      position: question.number,
      source: question.source,
      deal_breaker: stamped && !sameText(stamped, question.question) ? null : question.deal_breaker,
    };
  });
  const known = new Set(state.questions.map((question) => question.question_id).filter(Boolean));
  let position = rows.length;
  for (const answer of sheetAnswers) {
    if (known.has(answer.question_id)) continue;
    if (!(answer.response ?? "").trim() && !answer.skipped) continue;
    position += 1;
    rows.push({ ...answer, position, source: "sheet" });
  }
  return rows;
}

/** Zdanie ostrzeżenia o naruszonym „Odpada, gdy…” (`null` = brak trafień). */
export function screeningDealBreakerWarning(rows: readonly ScreeningAnswerRow[]): string | null {
  const hits = rows.filter((row) => row.deal_breaker_hit === true);
  if (!hits.length) return null;
  const numbers = hits.map((row, index) => row.position ?? index + 1).join(", ");
  return hits.length === 1
    ? `Odpowiedź na pytanie ${numbers} narusza „Odpada, gdy…”.`
    : `Odpowiedzi na pytania ${numbers} naruszają „Odpada, gdy…”.`;
}

/** „3 z 5” — ile pytań ma odpowiedź (`null`, gdy nie ma pytań). */
export function screeningAnsweredLabel(rows: readonly ScreeningAnswerRow[]): string | null {
  if (!rows.length) return null;
  const answered = rows.filter((row) => (row.response ?? "").trim()).length;
  return `${answered} z ${rows.length}`;
}

/** Podpowiedź pustego pola: wartość z poprzedniej próby albo z profilu. */
export function screeningFieldHint(card: Pick<ScreeningFormCard, "previous" | "suggestions">, key: string): string | null {
  const previous = String(card.previous?.[key]?.raw ?? "").trim();
  return previous || card.suggestions?.[key]?.trim() || null;
}

/** „komplet pól” / „brakuje 2” / „puste pola” — pola warunków i oceny. */
export function screeningFieldsLabel(
  completeness: { status: "complete" | "partial" | "empty"; missing: number } | null | undefined,
): string {
  if (!completeness || completeness.status === "empty") return "puste pola";
  if (completeness.status === "complete") return "komplet pól";
  return `brakuje ${completeness.missing}`;
}

/**
 * Podsumowanie zwiniętej sekcji „Screening” w doku: ocena rekrutera (gdy
 * arkusz jest już wczytany) i stan pól z karty Tablicy — bez zapytania.
 */
export function screeningSectionSummary(
  card: BoardCardState | null | undefined,
  fit: keyof typeof SCREENING_FIT_LABEL | null | undefined,
): string {
  if (!card && !fit) return "Pytania, warunki i ocena";
  const fields = screeningFieldsLabel(card);
  return fit ? `${SCREENING_FIT_LABEL[fit]} · ${fields}` : fields;
}
