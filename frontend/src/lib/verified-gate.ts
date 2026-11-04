/**
 * Bramka „Zweryfikowany” i powód ręcznego zatrudnienia (decyzje Artura
 * 04.10.2026, D1 i D2) — lustro `pipeline_move_rules` w backendzie.
 *
 * D1: wejście na „Zweryfikowany” z Nowych/Screeningu wymaga arkusza
 * screeningu (albo odpowiedzi w karcie rekomendacji) i stawki kandydata.
 * Rekrutacja bez pytań screeningowych nie ma arkusza do wypełnienia — tam
 * serwer wymaga „Dlaczego ten kandydat” (`why_candidate`, 12.10.2026).
 * Serwer odmawia 409 `VERIFIED_REQUIREMENTS_MISSING`; ekran otwiera to,
 * czego brakuje. Od 21.10.2026 także minimum dla Delivery Leada (`cardFields`).
 *
 * D2: ręczny ruch na „Zatrudniony” mówi, jak podpisano umowę. Umowa B2B
 * z Generatora przesuwa kartę sama („Oznacz jako podpisaną”).
 */

export type VerifiedRequirement = "screening_sheet" | "why_candidate" | "candidate_rate";

export interface VerifiedRequirementsMissing {
  missing: VerifiedRequirement[];
  /**
   * Pola karty z minimum dla Delivery Leada (21.10.2026): lokalizacja, tryb
   * pracy, dostępność, „Dlaczego ten kandydat” i pola dołożone przez klienta.
   * Klucze jak w formularzu screeningu (`card.<klucz>`).
   */
  cardFields: string[];
  /** Wiersz etapu, na którym otworzyć arkusz screeningu. */
  screeningStageId: number | null;
  message: string;
}

export function verifiedRequirementsOf(error: unknown): VerifiedRequirementsMissing | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response;
  const detail = response?.data?.detail as
    | {
        code?: unknown;
        missing?: unknown;
        card_fields?: unknown;
        screening_stage_id?: unknown;
        message?: unknown;
      }
    | undefined;
  if (response?.status !== 409 || !detail || detail.code !== "VERIFIED_REQUIREMENTS_MISSING") {
    return null;
  }
  const missing = Array.isArray(detail.missing)
    ? detail.missing.filter(
        (key): key is VerifiedRequirement =>
          key === "screening_sheet" || key === "why_candidate" || key === "candidate_rate",
      )
    : [];
  const cardFields = Array.isArray(detail.card_fields)
    ? detail.card_fields.filter((key): key is string => typeof key === "string" && key.trim() !== "")
    : [];
  return {
    missing,
    cardFields,
    screeningStageId:
      typeof detail.screening_stage_id === "number" ? detail.screening_stage_id : null,
    message:
      typeof detail.message === "string" && detail.message.trim()
        ? detail.message
        : "Przed „Zweryfikowany” uzupełnij arkusz screeningu i stawkę kandydata.",
  };
}

export type HiredSignedVia = "b2b_offline" | "uop" | "zlecenie" | "other";

export const HIRED_SIGNED_VIA_OPTIONS: ReadonlyArray<{ value: HiredSignedVia; label: string }> = [
  { value: "b2b_offline", label: "Umowa B2B podpisana poza Generatorem" },
  { value: "uop", label: "Umowa o pracę" },
  { value: "zlecenie", label: "Umowa zlecenie" },
  { value: "other", label: "Inna umowa" },
];

/**
 * „Co z obecną współpracą?” — pytanie w oknie zatrudnienia, gdy osoba ma już
 * trwającą umowę u innego klienta (12.10.2026). Odpowiedź dostaje Delivery
 * Lead tamtego klienta; umów ani zamówień nie zmienia.
 * Lustro `StageMove.hired_current_engagement`.
 */
export type HiredCurrentEngagement = "switch" | "parallel" | "ask_delivery_lead";

export const HIRED_CURRENT_ENGAGEMENT_OPTIONS: ReadonlyArray<{
  value: HiredCurrentEngagement;
  label: string;
}> = [
  { value: "switch", label: "Przechodzi do nowego klienta, obecna współpraca się kończy" },
  { value: "parallel", label: "Będzie pracować równolegle u obu klientów" },
  { value: "ask_delivery_lead", label: "Nie wiem — niech zdecyduje Delivery Lead" },
];

/** Czy wybór w oknie „Potwierdź zatrudnienie” wystarcza serwerowi. */
export function hiredReasonComplete(via: HiredSignedVia | null, note: string): boolean {
  if (via === null) return false;
  return via !== "other" || note.trim().length > 0;
}
