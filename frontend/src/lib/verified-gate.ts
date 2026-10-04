/**
 * Bramka „Zweryfikowany” i powód ręcznego zatrudnienia (decyzje Artura
 * 04.10.2026, D1 i D2) — lustro `pipeline_move_rules` w backendzie.
 *
 * D1: wejście na „Zweryfikowany” z Nowych/Screeningu wymaga arkusza
 * screeningu (albo odpowiedzi w karcie rekomendacji) i stawki kandydata.
 * Serwer odmawia 409 `VERIFIED_REQUIREMENTS_MISSING`; ekran otwiera to,
 * czego brakuje.
 *
 * D2: ręczny ruch na „Zatrudniony” mówi, jak podpisano umowę. Umowa B2B
 * z Generatora przesuwa kartę sama („Oznacz jako podpisaną”).
 */

export type VerifiedRequirement = "screening_sheet" | "candidate_rate";

export interface VerifiedRequirementsMissing {
  missing: VerifiedRequirement[];
  /** Wiersz etapu, na którym otworzyć arkusz screeningu. */
  screeningStageId: number | null;
  message: string;
}

export function verifiedRequirementsOf(error: unknown): VerifiedRequirementsMissing | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response;
  const detail = response?.data?.detail as
    | { code?: unknown; missing?: unknown; screening_stage_id?: unknown; message?: unknown }
    | undefined;
  if (response?.status !== 409 || !detail || detail.code !== "VERIFIED_REQUIREMENTS_MISSING") {
    return null;
  }
  const missing = Array.isArray(detail.missing)
    ? detail.missing.filter(
        (key): key is VerifiedRequirement => key === "screening_sheet" || key === "candidate_rate",
      )
    : [];
  return {
    missing,
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

/** Czy wybór w oknie „Potwierdź zatrudnienie” wystarcza serwerowi. */
export function hiredReasonComplete(via: HiredSignedVia | null, note: string): boolean {
  if (via === null) return false;
  return via !== "other" || note.trim().length > 0;
}
