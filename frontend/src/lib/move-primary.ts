/**
 * Co robi główny przycisk przejścia dalej — JEDNA reguła dla okna
 * „Przesuń dalej” (`MoveNextDialog`) i ramki „Następny etap” w doku osoby
 * (`DockNextStage`). Serwer mówi `primary.kind` (`GET /api/pipeline/move-requirements`),
 * a ta funkcja zamienia go na krok do wykonania. Do 24.09.2026 ramka w doku
 * ignorowała `primary` i zawsze przesuwała osobę na następną kolumnę — u Nordei
 * z pominięciem kolejki Cpro, a rekruterowi obiecywała wysyłkę, którą robi DL.
 */

import type { MoveRequirementsResponse } from "@/lib/api/moveRequirements";

// Kolejka Delivery Leada liczy tylko karty z zaliczonym (albo przepuszczonym)
// QC — do 14.10.2026 toast odsyłał do „Czeka na Ciebie”, której rekruter nie ma.
export const HAND_TO_DL_MESSAGE =
  "Osoba jest w „QC CV” — trafi do Delivery Leada, gdy QC przejdzie.";

export const NO_QC_STAGE_MESSAGE =
  "Szablon tej rekrutacji nie ma etapu „QC CV” — poproś Delivery Leada, żeby przesunął osobę dalej.";

export type PrimaryStep =
  /** Zwykły ruch na kolumnę docelową. */
  | { type: "move" }
  /** Ruch na wskazany etap szablonu (QC CV przy przekazaniu DL, etap Cpro). */
  | { type: "stage"; stageDefId: number; notice: string | null }
  /**
   * Nic do przesunięcia — osoba już stoi w „QC CV” i dalej prowadzi ją
   * Delivery Lead. Okno i ramka pokazują stan („Czeka u Delivery Leada od …”
   * albo co poprawić), bez głównego przycisku (14.10.2026).
   */
  | { type: "waiting" }
  | { type: "error"; message: string }
  | { type: "disabled" };

/**
 * `gaps` = liczba braków blokujących (`isBlockingGap`). Brak `primary`
 * (serwer nie odpowiedział) to „disabled” — wołający sam decyduje, czy przy
 * awarii wymagań przepuścić ruch (ramka i okno robią to jawnym przyciskiem).
 */
export function planPrimaryStep(
  data: Pick<MoveRequirementsResponse, "primary" | "from_column"> | null | undefined,
  gaps: number,
): PrimaryStep {
  const primary = data?.primary ?? null;
  if (!primary) return { type: "disabled" };
  switch (primary.kind) {
    case "hand_to_dl":
      // Przegląd DL czyta WYŁĄCZNIE kolumnę „QC CV” — osoba spoza niej nie
      // czeka u nikogo, więc „przekazanie” = ruch na etap QC CV szablonu.
      if (primary.target_stage_def_id != null) {
        return { type: "stage", stageDefId: primary.target_stage_def_id, notice: HAND_TO_DL_MESSAGE };
      }
      if (data?.from_column !== "cv_qc") return { type: "error", message: NO_QC_STAGE_MESSAGE };
      return { type: "waiting" };
    case "hand_to_cpro":
      if (primary.target_stage_def_id == null) return { type: "disabled" };
      return { type: "stage", stageDefId: primary.target_stage_def_id, notice: null };
    case "move":
      return gaps > 0 ? { type: "disabled" } : { type: "move" };
    default:
      return { type: "disabled" };
  }
}
